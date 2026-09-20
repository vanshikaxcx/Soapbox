"""Conversation, voice-session, and turn-audio use cases (WP-05-A1).

These are the tests that would catch a use case skipping a rule WP-02 already
decided: rebinding to a moved-on question, submitting twice, submitting after
expiry, or serving one owner's turn audio to another. Also covers the
idempotency-key handling added alongside the HTTP-handler follow-up: a retry
must replay, not duplicate, and a reused key with a different payload must
conflict.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services.application.conversation import (
    ConversationUseCases,
    NotFound,
    TurnAudioService,
    VoiceSessionOpened,
    VoiceSessionUseCases,
    conversation_key,
)
from services.application.fakes import (
    FixedClock,
    FixedTranscribeUrlSigner,
    MemoryAudioSink,
    MemoryStore,
    ScriptedSpeechSynthesizer,
    SequentialIds,
)
from services.domain.conversation import Conversation, InputKind, Speaker, Turn
from services.domain.errors import (
    DomainError,
    IdempotencyPayloadMismatch,
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


def a_conversation(
    world: World, owner_id: str = OWNER, idempotency: str = "idem-conv-1"
) -> Conversation:
    result = world.conversations.create_conversation(owner_id=owner_id, idempotency=idempotency)
    assert isinstance(result, Conversation)
    return result


def a_turn(world: World, conversation: Conversation, idempotency: str = "idem-turn-1") -> Turn:
    result = world.conversations.add_turn(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        speaker=Speaker.ASSISTANT,
        text="Got it, five kilos of rice.",
        input_kind=InputKind.TEXT,
        reply_to_question_id=None,
        audio_key=None,
        idempotency=idempotency,
    )
    assert isinstance(result, Turn)
    return result


def an_open_session(
    world: World, conversation: Conversation, idempotency: str = "idem-voice-1"
) -> VoiceSessionOpened:
    result = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
        idempotency=idempotency,
    )
    assert isinstance(result, VoiceSessionOpened)
    return result


# -- conversations and turns -------------------------------------------------


def test_creating_a_conversation_binds_it_to_its_owner() -> None:
    world = World()
    conversation = a_conversation(world)
    assert conversation.owner_id == OWNER
    assert conversation.version == 1


def test_creating_a_conversation_twice_with_the_same_key_replays() -> None:
    world = World()
    first = a_conversation(world, idempotency="same-key")
    second = a_conversation(world, idempotency="same-key")
    assert first.conversation_id == second.conversation_id


def test_reading_another_owners_conversation_is_not_found() -> None:
    world = World()
    conversation = a_conversation(world)
    result = world.conversations.read_conversation(
        owner_id=OTHER_OWNER, conversation_id=conversation.conversation_id
    )
    assert isinstance(result, NotFound)


def test_a_turn_is_recorded_against_its_conversation() -> None:
    world = World()
    conversation = a_conversation(world)
    turn = a_turn(world, conversation)
    assert turn.text == "Got it, five kilos of rice."


def test_adding_the_same_turn_twice_with_the_same_key_replays() -> None:
    world = World()
    conversation = a_conversation(world)
    first = a_turn(world, conversation, idempotency="same-key")
    second = a_turn(world, conversation, idempotency="same-key")
    assert first.turn_id == second.turn_id


def test_reusing_a_turn_key_with_a_different_payload_conflicts() -> None:
    world = World()
    conversation = a_conversation(world)
    a_turn(world, conversation, idempotency="same-key")
    result = world.conversations.add_turn(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        speaker=Speaker.SHOPPER,  # different payload, same key
        text="a completely different turn",
        input_kind=InputKind.TEXT,
        reply_to_question_id=None,
        audio_key=None,
        idempotency="same-key",
    )
    assert isinstance(result, IdempotencyPayloadMismatch)


# -- voice sessions -----------------------------------------------------------


def test_opening_a_session_issues_a_real_presigned_url() -> None:
    world = World()
    conversation = a_conversation(world)
    opened = an_open_session(world, conversation)
    assert opened.wss_url.startswith("wss://")
    assert world.signer.calls == [("en-IN", 16_000)]


def test_opening_a_session_twice_with_the_same_key_replays_the_same_record() -> None:
    world = World()
    conversation = a_conversation(world)
    first = an_open_session(world, conversation, idempotency="same-key")
    second = an_open_session(world, conversation, idempotency="same-key")
    assert first.session.voice_session_id == second.session.voice_session_id
    # Presigning is stateless: a replay still gets a usable URL, not a
    # placeholder, even though no second session record was created.
    assert second.wss_url.startswith("wss://")
    assert world.signer.calls == [("en-IN", 16_000), ("en-IN", 16_000)]


def test_opening_a_session_against_a_stale_version_is_a_conflict() -> None:
    world = World()
    conversation = a_conversation(world)
    result = world.voice.open_session(
        owner_id=OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version + 1,
        idempotency="idem-1",
    )
    assert isinstance(result, VersionConflict)


def test_opening_a_session_for_another_owners_conversation_is_not_found() -> None:
    world = World()
    conversation = a_conversation(world)
    result = world.voice.open_session(
        owner_id=OTHER_OWNER,
        conversation_id=conversation.conversation_id,
        conversation_version=conversation.version,
        idempotency="idem-1",
    )
    assert isinstance(result, NotFound)


def test_submitting_once_records_the_transcript_hash() -> None:
    world = World()
    conversation = a_conversation(world)
    opened = an_open_session(world, conversation)

    submitted = world.voice.submit(
        owner_id=OWNER,
        voice_session_id=opened.session.voice_session_id,
        transcript="five kilos of rice",
    )
    assert not isinstance(submitted, DomainError)
    assert submitted.submitted_transcript_hash is not None


def test_a_second_submit_is_not_a_retry_of_the_first() -> None:
    world = World()
    conversation = a_conversation(world)
    opened = an_open_session(world, conversation)
    session_id = opened.session.voice_session_id

    world.voice.submit(owner_id=OWNER, voice_session_id=session_id, transcript="first")
    second = world.voice.submit(owner_id=OWNER, voice_session_id=session_id, transcript="second")
    assert isinstance(second, VoiceSessionAlreadyResolved)


def test_submitting_after_expiry_is_rejected_not_applied() -> None:
    world = World()
    conversation = a_conversation(world)
    opened = an_open_session(world, conversation)

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
    conversation = a_conversation(world)
    opened = an_open_session(world, conversation)

    moved_on = conversation.model_copy(update={"version": conversation.version + 1})
    world.store.seed(conversation_key(conversation.conversation_id), moved_on)

    result = world.voice.submit(
        owner_id=OWNER, voice_session_id=opened.session.voice_session_id, transcript="stale"
    )
    assert isinstance(result, VoiceSessionExpired)


def test_cancelling_an_open_session_then_submitting_is_resolved_not_expired() -> None:
    world = World()
    conversation = a_conversation(world)
    opened = an_open_session(world, conversation)

    world.voice.cancel(owner_id=OWNER, voice_session_id=opened.session.voice_session_id)
    result = world.voice.submit(
        owner_id=OWNER, voice_session_id=opened.session.voice_session_id, transcript="too late"
    )
    assert isinstance(result, VoiceSessionAlreadyResolved)


# -- turn audio ---------------------------------------------------------------


def test_first_playback_synthesizes_and_caches_the_audio_key() -> None:
    world = World()
    conversation = a_conversation(world)
    turn = a_turn(world, conversation)

    url = world.audio.playback_url(
        owner_id=OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    assert isinstance(url, str)
    assert world.synthesizer.synthesize_calls == ["Got it, five kilos of rice."]
    assert world.sink.save_calls == 1


def test_second_playback_reuses_the_cached_key_without_resynthesizing() -> None:
    world = World()
    conversation = a_conversation(world)
    turn = a_turn(world, conversation)

    world.audio.playback_url(
        owner_id=OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    world.audio.playback_url(
        owner_id=OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    assert world.synthesizer.synthesize_calls == ["Got it, five kilos of rice."]  # only once
    assert world.sink.save_calls == 1


def test_playback_for_another_owners_turn_is_not_found() -> None:
    world = World()
    conversation = a_conversation(world)
    turn = a_turn(world, conversation)

    result = world.audio.playback_url(
        owner_id=OTHER_OWNER, conversation_id=conversation.conversation_id, turn_id=turn.turn_id
    )
    assert isinstance(result, NotFound)
