"""Inbox deduplication and case gaps (WP-02 support for WP-09/WP-10)."""

from __future__ import annotations

from datetime import UTC, datetime

from services.domain.evidence import (
    Case,
    FactKind,
    InboxEvent,
    MissingFact,
    is_conflicting,
    is_duplicate,
)
from services.domain.transitions import CaseState, InboxState

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
BODY_A = "a" * 64
BODY_B = "b" * 64


def an_event(body_hash: str = BODY_A) -> InboxEvent:
    return InboxEvent(
        provider="sim",
        event_id="evt-0001",
        body_hash=body_hash,
        delivery_timestamp=NOW,
        received_at=NOW,
        kind=FactKind.PAYMENT,
        key="payment-key-1",
    )


def test_a_redelivery_of_the_same_bytes_is_a_duplicate() -> None:
    assert is_duplicate(an_event(), BODY_A) is True
    assert is_conflicting(an_event(), BODY_A) is False


def test_the_same_event_id_with_different_bytes_conflicts() -> None:
    """Never applied: someone is replaying an id with a changed body."""
    assert is_conflicting(an_event(), BODY_B) is True
    assert is_duplicate(an_event(), BODY_B) is False


def test_an_inbox_event_starts_as_received() -> None:
    assert an_event().status is InboxState.RECEIVED


def test_an_inbox_event_is_immutable() -> None:
    assert InboxEvent.model_config.get("frozen") is True


def a_case(missing: tuple[MissingFact, ...] = ()) -> Case:
    return Case(
        case_id="case-0001",
        purchase_id="purchase-01",
        owner_id="owner-0001",
        opened_at=NOW,
        missing_facts=missing,
    )


def test_a_new_case_is_open() -> None:
    assert a_case().status is CaseState.OPEN


def test_missing_facts_are_named_rather_than_left_absent() -> None:
    """ "We don't know whether an order exists" is the thing to say out loud."""
    case = a_case((MissingFact.ORDER_EXISTENCE,))
    assert case.has_gaps is True
    assert MissingFact.ORDER_EXISTENCE in case.missing_facts


def test_a_case_with_no_gaps_reports_none() -> None:
    assert a_case().has_gaps is False


def test_the_paid_but_order_missing_shape_is_expressible() -> None:
    case = Case(
        case_id="case-0001",
        purchase_id="purchase-01",
        owner_id="owner-0001",
        opened_at=NOW,
        known_facts=(FactKind.PAYMENT,),
        missing_facts=(MissingFact.ORDER_EXISTENCE, MissingFact.ORDER_REFERENCE),
    )
    assert FactKind.PAYMENT in case.known_facts
    assert FactKind.ORDER not in case.known_facts
    assert case.has_gaps
