"""Conversation, voice-session, and turn-audio use cases (WP-05-A1).

These are the tests that would catch a use case skipping a rule WP-02 already
decided: rebinding to a moved-on question, submitting twice, submitting after
expiry, or serving one owner's turn audio to another.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services.application.conversation import (
    ConversationUseCases,
    NotFound,
    TurnAudioService,
    VoiceSessionOpened,
    VoiceSessionUseCases,
)
from services.application.fakes import (
    FixedClock,
    FixedTranscribeUrlSigner,
    MemoryAudioSink,
    MemoryStore,
    ScriptedSpeechSynthesizer,
    SequentialIds,
)
from services.domain.conversation import InputKind, Speaker
from services.domain.errors import (
    DomainError,
    VersionConflict,
    VoiceSessionAlreadyResolved,
    VoiceSessionExpired,
)

OWNER = "owner-00000001"
OTHER_OWNER = "owner-00000002"


class World:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        self.ids = SequentialIds()
        self.conversations = ConversationUseCases(store=self.store, clock=self.clock, ids=self.ids)
        self.signer = FixedTranscribeUrlSigner()
        self.voice = VoiceSessionUseCases(
            store=self.store, clock=self.clock, ids=self.ids, signer=self.signer
        )
        self.synthesizer = ScriptedSpeechSynthesizer()
        self.sink = MemoryAudioSink()
        self.audio = TurnAudioService(
            conversations=self.conversations,
            store=self.store,
            synthesizer=self.synthesizer,
            sink=self.sink,
        )


# -- conversations and turns -------------------------------------------------


def test_creating_a_conversation_binds_it_to_its_owner() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    assert conversation.owner_id == OWNER
    assert conversation.version == 1


def test_reading_another_owners_conversation_is_not_found() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    result = world.conversations.read_conversation(
        owner_id=OTHER_OWNER, conversation_id=conversation.conversation_id
    )
    assert isinstance(result, NotFound)


def test_a_turn_is_recorded_against_its_conversation() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    turn = world.conversations.add_turn(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        speaker=Speaker.SHOPPER,
        text="five kilos of rice",
        input_kind=InputKind.TEXT,
        reply_to_question_id=None,
        audio_key=None,
    )
    assert not isinstance(turn, DomainError)
    assert turn.text == "five kilos of rice"


# -- voice sessions -----------------------------------------------------------


def test_opening_a_session_issues_a_real_presigned_url() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    opened = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
    )
    assert isinstance(opened, VoiceSessionOpened)
    assert opened.wss_url.startswith("wss://")
    assert world.signer.calls == [("en-IN", 16_000)]


def test_opening_a_session_against_a_stale_version_is_a_conflict() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    result = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version + 1,
    )
    assert isinstance(result, VersionConflict)


def test_opening_a_session_for_another_owners_conversation_is_not_found() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    result = world.voice.open_session(
        owner_id=OTHER_OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
    )
    assert isinstance(result, NotFound)


def test_submitting_once_records_the_transcript_hash() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    opened = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
    )
    assert isinstance(opened, VoiceSessionOpened)

    submitted = world.voice.submit(
        owner_id=OWNER,
        voice_session_id=opened.session.voice_session_id,
        transcript="five kilos of rice",
    )
    assert not isinstance(submitted, DomainError)
    assert submitted.submitted_transcript_hash is not None


def test_a_second_submit_is_not_a_retry_of_the_first() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    opened = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
    )
    assert isinstance(opened, VoiceSessionOpened)
    session_id = opened.session.voice_session_id

    world.voice.submit(owner_id=OWNER, voice_session_id=session_id, transcript="first")
    second = world.voice.submit(owner_id=OWNER, voice_session_id=session_id, transcript="second")
    assert isinstance(second, VoiceSessionAlreadyResolved)


def test_submitting_after_expiry_is_rejected_not_applied() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    opened = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
    )
    assert isinstance(opened, VoiceSessionOpened)

    world.clock.advance(61)  # the product spec's one-utterance-<=60s cap
    result = world.voice.submit(
        owner_id=OWNER, voice_session_id=opened.session.voice_session_id, transcript="too late"
    )
    assert isinstance(result, VoiceSessionExpired)


def test_the_conversation_moving_on_rejects_a_late_transcript() -> None:
    """WP-02's own rule: a session cannot be rebound to a newer question than
    the one it captured. Simulated here by advancing the conversation's
    version directly on the store between opening and submitting."""
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    opened = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
    )
    assert isinstance(opened, VoiceSessionOpened)

    from services.application.conversation import conversation_key

    moved_on = conversation.model_copy(update={"version": conversation.version + 1})
    world.store.seed(conversation_key(conversation.conversation_id), moved_on)

    result = world.voice.submit(
        owner_id=OWNER, voice_session_id=opened.session.voice_session_id, transcript="stale"
    )
    assert isinstance(result, VoiceSessionExpired)


def test_cancelling_an_open_session_then_submitting_is_resolved_not_expired() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    opened = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
    )
    assert isinstance(opened, VoiceSessionOpened)

    world.voice.cancel(owner_id=OWNER, voice_session_id=opened.session.voice_session_id)
    result = world.voice.submit(
        owner_id=OWNER, voice_session_id=opened.session.voice_session_id, transcript="too late"
    )
    assert isinstance(result, VoiceSessionAlreadyResolved)


# -- turn audio ---------------------------------------------------------------


def test_first_playback_synthesizes_and_caches_the_audio_key() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    turn = world.conversations.add_turn(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        speaker=Speaker.ASSISTANT,
        text="Got it, five kilos of rice.",
        input_kind=InputKind.TEXT,
        reply_to_question_id=None,
        audio_key=None,
    )
    assert not isinstance(turn, DomainError)

    url = world.audio.playback_url(
        owner_id=OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    assert isinstance(url, str)
    assert world.synthesizer.synthesize_calls == ["Got it, five kilos of rice."]
    assert world.sink.save_calls == 1


def test_second_playback_reuses_the_cached_key_without_resynthesizing() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    turn = world.conversations.add_turn(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        speaker=Speaker.ASSISTANT,
        text="Got it.",
        input_kind=InputKind.TEXT,
        reply_to_question_id=None,
        audio_key=None,
    )
    assert not isinstance(turn, DomainError)

    world.audio.playback_url(
        owner_id=OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    world.audio.playback_url(
        owner_id=OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    assert world.synthesizer.synthesize_calls == ["Got it."]  # only once
    assert world.sink.save_calls == 1


def test_playback_for_another_owners_turn_is_not_found() -> None:
    world = World()
    conversation = world.conversations.create_conversation(owner_id=OWNER)
    turn = world.conversations.add_turn(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        speaker=Speaker.ASSISTANT,
        text="Got it.",
        input_kind=InputKind.TEXT,
        reply_to_question_id=None,
        audio_key=None,
    )
    assert not isinstance(turn, DomainError)

    result = world.audio.playback_url(
        owner_id=OTHER_OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    assert isinstance(result, NotFound)
