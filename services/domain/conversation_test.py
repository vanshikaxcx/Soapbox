"""Conversation and voice-session binding (WP-02 structural rules).

Behaviour is P1's in WP-05; what is asserted here is the part that has to be
agreed once: a voice session cannot be rebound to a newer question than the one
it captured, and it submits at most once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.domain.conversation import (
    VoiceSession,
    VoiceSessionStatus,
    binding_is_current,
    is_expired,
    may_submit,
)

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def a_session(
    *,
    conversation_version: int = 3,
    question_id: str | None = "question-01",
    status: VoiceSessionStatus = VoiceSessionStatus.OPEN,
    transcript_hash: str | None = None,
    expires_at: datetime | None = None,
) -> VoiceSession:
    return VoiceSession(
        voice_session_id="voice-0001",
        owner_id="owner-0001",
        conversation_id="conversation-01",
        conversation_version=conversation_version,
        question_id=question_id,
        expires_at=expires_at or NOW + timedelta(seconds=60),
        status=status,
        submitted_transcript_hash=transcript_hash,
    )


# -- binding ---------------------------------------------------------------


def test_a_session_is_current_against_the_context_it_captured() -> None:
    assert binding_is_current(
        a_session(), conversation_version=3, active_question_id="question-01"
    )


def test_a_session_is_stale_once_the_conversation_moves_on() -> None:
    """Someone spoke while the conversation advanced; the answer must not land."""
    assert not binding_is_current(
        a_session(), conversation_version=4, active_question_id="question-01"
    )


def test_a_session_cannot_be_rebound_to_a_newer_question() -> None:
    assert not binding_is_current(
        a_session(question_id="question-01"),
        conversation_version=3,
        active_question_id="question-02",
    )


def test_a_free_form_session_is_only_current_when_no_question_is_active() -> None:
    free_form = a_session(question_id=None)
    assert binding_is_current(free_form, conversation_version=3, active_question_id=None)
    assert not binding_is_current(
        free_form, conversation_version=3, active_question_id="question-01"
    )


# -- submission ------------------------------------------------------------


def test_an_open_unexpired_session_may_submit() -> None:
    assert may_submit(a_session(), NOW) is True


def test_a_session_submits_only_once() -> None:
    already = a_session(transcript_hash="a" * 64)
    assert may_submit(already, NOW) is False


@pytest.mark.parametrize(
    "status",
    [VoiceSessionStatus.SUBMITTED, VoiceSessionStatus.CANCELLED, VoiceSessionStatus.EXPIRED],
)
def test_a_closed_session_may_not_submit(status: VoiceSessionStatus) -> None:
    assert may_submit(a_session(status=status), NOW) is False


def test_an_expired_session_may_not_submit() -> None:
    session = a_session(expires_at=NOW)
    assert may_submit(session, NOW) is False


# -- expiry boundary matches quotes and preparations -----------------------


@pytest.mark.parametrize(
    ("offset", "expired"), [(-1, False), (0, True), (1, True)]
)
def test_expiry_is_inclusive_at_the_boundary(offset: int, expired: bool) -> None:
    assert is_expired(NOW, NOW + timedelta(seconds=offset)) is expired
