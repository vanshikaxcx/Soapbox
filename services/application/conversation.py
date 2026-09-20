"""Conversation, turn, voice-session, and turn-audio use cases (WP-05-A1).

Ordering, authorization and transaction assembly only -- every rule about
expiry, rebinding and submit-once is WP-02's, in
``services/domain/conversation.py``, unchanged and re-used verbatim here.

P4 supplies this slice per the WP-05 implementation split: "P4 supplies
presigned Transcribe/S3 and Polly adapter endpoints through reviewed ports."
P1's UI talks to this instead of its fixtures; the agent's schema-bound
extraction (P2's ``/tasks/extract``) is not called from here -- that needs
WP-07's still-missing public route (out of scope, tracked separately).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

from services.application.ports import Clock, Condition, IdFactory, StateStore, Write, read
from services.application.ports.speech import (
    AudioSink,
    SpeechSynthesisResult,
    SpeechSynthesizer,
    TranscribeUrlSigner,
)
from services.domain.canonical import TAG_VOICE_TRANSCRIPT, digest
from services.domain.conversation import (
    Conversation,
    InputKind,
    Speaker,
    Turn,
    VoiceSession,
    VoiceSessionStatus,
    binding_is_current,
    is_expired,
    may_submit,
)
from services.domain.errors import DomainError, VersionConflict
from services.domain.errors import VoiceSessionAlreadyResolved as SessionAlreadyResolved
from services.domain.errors import VoiceSessionExpired as SessionExpired
from services.domain.ids import Record

_VOICE_SESSION_TTL_SECONDS = 60  # one utterance, per the product spec's cap


def conversation_key(conversation_id: str) -> tuple[str, str]:
    return (f"CONVERSATION#{conversation_id}", "CONVERSATION")


def turn_key(conversation_id: str, turn_id: str) -> tuple[str, str]:
    return (f"CONVERSATION#{conversation_id}", f"TURN#{turn_id}")


def voice_session_key(voice_session_id: str) -> tuple[str, str]:
    return (f"VOICE#{voice_session_id}", "SESSION")


@dataclass(frozen=True, slots=True)
class NotFound(DomainError):
    """Owner mismatch and genuinely-absent records are indistinguishable."""

    code: ClassVar[str] = "not_found"
    what: str


class VoiceSessionOpened(Record):
    session: VoiceSession
    wss_url: str


class ConversationUseCases:
    """Create and read conversations; record turns. No agent call, no rules."""

    def __init__(self, *, store: StateStore, clock: Clock, ids: IdFactory) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def create_conversation(self, *, owner_id: str) -> Conversation:
        conversation = Conversation(
            conversation_id=self._ids.new_id("conversation"), owner_id=owner_id
        )
        self._store.transact(
            [
                Write(
                    key=conversation_key(conversation.conversation_id),
                    item=conversation,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="create the conversation once",
                )
            ]
        )
        return conversation

    def read_conversation(
        self, *, owner_id: str, conversation_id: str
    ) -> Conversation | DomainError:
        conversation = read(self._store, conversation_key(conversation_id), Conversation)
        if conversation is None or conversation.owner_id != owner_id:
            return NotFound("conversation")
        return conversation

    def add_turn(
        self,
        *,
        owner_id: str,
        conversation_id: str,
        speaker: Speaker,
        text: str,
        input_kind: InputKind,
        reply_to_question_id: str | None,
        audio_key: str | None,
    ) -> Turn | DomainError:
        conversation = self.read_conversation(owner_id=owner_id, conversation_id=conversation_id)
        if isinstance(conversation, DomainError):
            return conversation

        turn = Turn(
            turn_id=self._ids.new_id("turn"),
            conversation_id=conversation_id,
            speaker=speaker,
            text=text,
            input_kind=input_kind,
            reply_to_question_id=reply_to_question_id,
            audio_key=audio_key,
            created_at=self._clock.now(),
        )
        self._store.transact(
            [
                Write(
                    key=turn_key(conversation_id, turn.turn_id),
                    item=turn,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="record the turn once",
                )
            ]
        )
        return turn

    def read_turn(self, *, owner_id: str, conversation_id: str, turn_id: str) -> Turn | DomainError:
        conversation = self.read_conversation(owner_id=owner_id, conversation_id=conversation_id)
        if isinstance(conversation, DomainError):
            return conversation
        turn = read(self._store, turn_key(conversation_id, turn_id), Turn)
        if turn is None:
            return NotFound("turn")
        return turn


class VoiceSessionUseCases:
    """Issue, submit and cancel voice sessions. Never touches the transcript's
    meaning -- only whether this session may still accept one."""

    def __init__(
        self, *, store: StateStore, clock: Clock, ids: IdFactory, signer: TranscribeUrlSigner
    ) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids
        self._signer = signer

    def open_session(
        self,
        *,
        owner_id: str,
        conversation_id: str,
        conversation_version: int,
        question_id: str | None = None,
        target_id: str | None = None,
        target_version: int | None = None,
        intent_id: str | None = None,
        intent_revision: int | None = None,
        language: str = "en-IN",
    ) -> VoiceSessionOpened | DomainError:
        conversation = read(self._store, conversation_key(conversation_id), Conversation)
        if conversation is None or conversation.owner_id != owner_id:
            return NotFound("conversation")
        if conversation.version != conversation_version:
            return VersionConflict(expected=conversation_version, actual=conversation.version)
        if question_id != conversation.active_question_id:
            # Rebinding to a question the conversation has already moved past
            # is exactly what WP-02's binding rule exists to prevent.
            return NotFound("question")

        now = self._clock.now()
        session = VoiceSession(
            voice_session_id=self._ids.new_id("voice"),
            owner_id=owner_id,
            conversation_id=conversation_id,
            conversation_version=conversation_version,
            question_id=question_id,
            target_id=target_id,
            target_version=target_version,
            intent_id=intent_id,
            intent_revision=intent_revision,
            language=language,
            expires_at=now + timedelta(seconds=_VOICE_SESSION_TTL_SECONDS),
        )
        self._store.transact(
            [
                Write(
                    key=voice_session_key(session.voice_session_id),
                    item=session,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="create the voice session once",
                )
            ]
        )
        presigned = self._signer.presign(
            language_code=language,
            media_sample_rate_hz=16_000,
            expires_in_seconds=_VOICE_SESSION_TTL_SECONDS,
        )
        return VoiceSessionOpened(session=session, wss_url=presigned.url)

    def submit(
        self, *, owner_id: str, voice_session_id: str, transcript: str
    ) -> VoiceSession | DomainError:
        session = read(self._store, voice_session_key(voice_session_id), VoiceSession)
        if session is None or session.owner_id != owner_id:
            return NotFound("voice_session")

        now = self._clock.now()
        if not may_submit(session, now):
            if is_expired(session.expires_at, now):
                return SessionExpired(voice_session_id=voice_session_id)
            return SessionAlreadyResolved(voice_session_id=voice_session_id)

        conversation = read(self._store, conversation_key(session.conversation_id), Conversation)
        if conversation is None or not binding_is_current(
            session,
            conversation_version=conversation.version,
            active_question_id=conversation.active_question_id,
        ):
            # The conversation moved on while they were speaking. The
            # transcript is rejected rather than applied to a question they
            # never heard -- WP-02's rule, not a new one.
            return SessionExpired(voice_session_id=voice_session_id)

        updated = session.model_copy(
            update={
                "status": VoiceSessionStatus.SUBMITTED,
                "submitted_transcript_hash": digest(TAG_VOICE_TRANSCRIPT, transcript),
            }
        )
        self._store.transact(
            [
                Write(
                    key=voice_session_key(voice_session_id),
                    item=updated,
                    reason="record the submitted transcript's hash",
                )
            ]
        )
        return updated

    def cancel(self, *, owner_id: str, voice_session_id: str) -> VoiceSession | DomainError:
        session = read(self._store, voice_session_key(voice_session_id), VoiceSession)
        if session is None or session.owner_id != owner_id:
            return NotFound("voice_session")
        if session.status is not VoiceSessionStatus.OPEN:
            return SessionAlreadyResolved(voice_session_id=voice_session_id)

        updated = session.model_copy(update={"status": VoiceSessionStatus.CANCELLED})
        self._store.transact(
            [
                Write(
                    key=voice_session_key(voice_session_id),
                    item=updated,
                    reason="cancel the session",
                )
            ]
        )
        return updated


class TurnAudioService:
    """Synthesize a turn's spoken caption once, then always serve the same key.

    Polly synthesis is fast enough to run synchronously in-request; there is
    no job queue here. If synthesis latency becomes a real problem this
    becomes an async job -- deliberately not built until that is true.
    """

    def __init__(
        self,
        *,
        conversations: ConversationUseCases,
        store: StateStore,
        synthesizer: SpeechSynthesizer,
        sink: AudioSink,
    ) -> None:
        self._conversations = conversations
        self._store = store
        self._synthesizer = synthesizer
        self._sink = sink

    def playback_url(
        self, *, owner_id: str, conversation_id: str, turn_id: str, expires_in_seconds: int = 300
    ) -> str | DomainError:
        turn = self._conversations.read_turn(
            owner_id=owner_id, conversation_id=conversation_id, turn_id=turn_id
        )
        if isinstance(turn, DomainError):
            return turn

        if turn.audio_key is not None:
            return self._sink.playback_url(turn.audio_key, expires_in_seconds)

        result = self._synthesizer.synthesize(text=turn.text)
        if not isinstance(result, SpeechSynthesisResult):
            return NotFound(
                "audio"
            )  # synthesis failed; caller sees a typed 404 rather than a guessed code

        audio_key = self._sink.save(turn_id, result.audio_bytes, result.content_type)
        updated = turn.model_copy(update={"audio_key": audio_key})
        self._store.transact(
            [
                Write(
                    key=turn_key(conversation_id, turn_id),
                    item=updated,
                    reason="cache the synthesized audio key",
                )
            ]
        )
        return self._sink.playback_url(audio_key, expires_in_seconds)


__all__ = [
    "ConversationUseCases",
    "NotFound",
    "TurnAudioService",
    "VoiceSessionOpened",
    "VoiceSessionUseCases",
    "conversation_key",
    "turn_key",
    "voice_session_key",
]
