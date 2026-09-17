"""Conversation, turn, question and voice-session records (WP-02).

WP-02 owns the *shapes*, so every package shares one type. The interaction
behaviour -- one active question, transcript editing, playback, stale answers --
is P1's in WP-05. What lives here is the part that has to be agreed once and
cannot be re-decided per caller: version binding, expiry, and the rule that a
voice session cannot be rebound to a newer question than the one it captured.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from services.domain.ids import Digest, Id, Record, Timestamped


class InputKind(StrEnum):
    VOICE = "voice"
    TEXT = "text"
    PHOTO = "photo"
    USUAL_BASKET = "usual_basket"


class Speaker(StrEnum):
    SHOPPER = "shopper"
    ASSISTANT = "assistant"


class QuestionKind(StrEnum):
    """The closed set of things the assistant may ask.

    None of these mutates a purchase, an approval or an attempt. WP-08 asserts
    that structurally: a conversation answer can never become a payment approval.
    """

    MISSING_LOCATION = "missing_location"
    MISSING_QUANTITY = "missing_quantity"
    MISSING_PREFERENCE = "missing_preference"
    CONFIRM_EXTRACTED_LIST = "confirm_extracted_list"
    CONFIRM_SUBSTITUTION = "confirm_substitution"
    RELAX_CONSTRAINT = "relax_constraint"
    CHOOSE_MERCHANT = "choose_merchant"


#: Enumerated so WP-08's guard can assert the intersection with purchase-mutating
#: actions is empty, rather than relying on nobody adding a bad one later.
PURCHASE_MUTATING_QUESTION_KINDS: frozenset[QuestionKind] = frozenset()


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class VoiceSessionStatus(StrEnum):
    OPEN = "open"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Conversation(Record):
    conversation_id: Id
    owner_id: Id
    active_question_id: Id | None = None
    version: int = Field(default=1, ge=1)


class Turn(Timestamped):
    turn_id: Id
    conversation_id: Id
    speaker: Speaker
    text: str = Field(max_length=4000)
    input_kind: InputKind
    reply_to_question_id: Id | None = None
    audio_key: str | None = None
    created_at: datetime


class Question(Timestamped):
    question_id: Id
    conversation_id: Id
    kind: QuestionKind
    choices: tuple[str, ...] = ()
    proposed_change: str | None = None
    target_id: Id
    target_version: int = Field(ge=1)
    intent_revision: int | None = Field(default=None, ge=1)
    expires_at: datetime
    status: QuestionStatus = QuestionStatus.OPEN


class VoiceSession(Timestamped):
    """A microphone session bound to the context that existed when it opened.

    The binding is captured at creation and never updated. If the conversation
    moves on while someone is speaking, the transcript lands against a stale
    binding and is rejected, rather than being applied to a question the speaker
    never heard.
    """

    voice_session_id: Id
    owner_id: Id
    conversation_id: Id
    conversation_version: int = Field(ge=1)
    question_id: Id | None = None
    target_id: Id | None = None
    target_version: int | None = Field(default=None, ge=1)
    intent_id: Id | None = None
    intent_revision: int | None = Field(default=None, ge=1)
    language: str = Field(default="en-IN", min_length=2, max_length=16)
    expires_at: datetime
    status: VoiceSessionStatus = VoiceSessionStatus.OPEN
    submitted_transcript_hash: Digest | None = None


def is_expired(expires_at: datetime, now: datetime) -> bool:
    """Expired at the boundary, matching quote and preparation semantics."""
    return now >= expires_at


def binding_is_current(
    session: VoiceSession, *, conversation_version: int, active_question_id: str | None
) -> bool:
    """True when the session still refers to the context it captured.

    A session can never be rebound to a newer question: it is only valid against
    the conversation version and question it was opened for.
    """
    if session.conversation_version != conversation_version:
        return False
    return session.question_id == active_question_id


def may_submit(session: VoiceSession, now: datetime) -> bool:
    """A session submits once, before it expires."""
    if session.status is not VoiceSessionStatus.OPEN:
        return False
    if session.submitted_transcript_hash is not None:
        return False
    return not is_expired(session.expires_at, now)


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Conversation",
    "InputKind",
    "PURCHASE_MUTATING_QUESTION_KINDS",
    "Question",
    "QuestionKind",
    "QuestionStatus",
    "Speaker",
    "Turn",
    "VoiceSession",
    "VoiceSessionStatus",
    "binding_is_current",
    "is_expired",
    "may_submit",
]
