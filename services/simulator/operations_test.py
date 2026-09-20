"""The simulator's ledger rules (WP-09 acceptance criteria 1, 4, 5, 6).

The claim under test: one approval can produce at most one effect, no matter how
many times it is submitted, resent or replayed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from services.application.fakes import FixedClock, SequentialIds
from services.application.ports import Clock
from services.domain.errors import PaymentKeyConflict
from services.domain.money import Money
from services.simulator.ledger import LedgerStatus, PaymentRecord, Scenario
from services.simulator.operations import (
    NotFound,
    OrderRequest,
    ResponseLost,
    Simulator,
    SubmitRequest,
)

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(seconds=120)


def a_simulator(scenario: Scenario = Scenario.SUCCESS, *, clock: Clock | None = None) -> Simulator:
    return Simulator(clock=clock or FixedClock(NOW), ids=SequentialIds(), scenario=scenario)


def a_request(**over: Any) -> SubmitRequest:
    base: dict[str, Any] = dict(
        payment_key="a" * 64,
        request_hash="b" * 64,
        quote_hash="c" * 64,
        seller_id="demo-seller-01",
        amount=Money.paise(59_000),
        expires_at=EXPIRY,
    )
    base.update(over)
    return SubmitRequest(**base)


def paid(result: PaymentRecord | PaymentKeyConflict) -> PaymentRecord:
    """Narrow a submit the test expects the simulator to have accepted."""
    assert isinstance(result, PaymentRecord), f"the simulator refused it: {result}"
    return result


# -- one key, one effect ---------------------------------------------------


def test_a_submission_records_one_effect() -> None:
    sim = a_simulator()
    result = sim.submit(a_request())
    assert isinstance(result, PaymentRecord)
    assert result.effect_recorded is True
    assert sim.effect_count() == 1


def test_fifty_identical_replays_record_one_effect() -> None:
    sim = a_simulator()
    results = [paid(sim.submit(a_request())) for _ in range(50)]
    assert sim.effect_count() == 1
    assert len({r.provider_reference for r in results}) == 1
    assert sim.duplicate_submissions_suppressed == 49


def test_an_identical_replay_returns_the_original_facts() -> None:
    sim = a_simulator()
    first = sim.submit(a_request())
    second = sim.submit(a_request())
    assert second == first


def test_a_replay_after_expiry_still_returns_the_original_facts() -> None:
    """Otherwise a slow retry would be told a succeeded payment had failed."""
    clock = FixedClock(NOW)
    sim = a_simulator(clock=clock)
    first = sim.submit(a_request())

    clock.advance(600)
    replayed = sim.submit(a_request())
    assert replayed == first
    assert sim.effect_count() == 1


# -- a changed payload is a different request ------------------------------


def test_the_same_key_with_a_different_payload_conflicts() -> None:
    sim = a_simulator()
    sim.submit(a_request())
    conflict = sim.submit(a_request(request_hash="d" * 64))
    assert isinstance(conflict, PaymentKeyConflict)
    assert sim.effect_count() == 1, "a conflict records nothing"


def test_a_conflict_leaves_the_original_untouched() -> None:
    sim = a_simulator()
    original = sim.submit(a_request())
    sim.submit(a_request(request_hash="d" * 64, amount=Money.paise(1)))
    assert sim.query(payment_key="a" * 64) == original


def test_identity_is_checked_before_expiry() -> None:
    """An accepted payment must never be retro-rejected by a later replay."""
    clock = FixedClock(NOW)
    sim = a_simulator(clock=clock)
    accepted = sim.submit(a_request())
    clock.advance(1000)
    assert sim.submit(a_request()) == accepted


# -- expiry ----------------------------------------------------------------


def test_an_unseen_key_past_its_expiry_is_rejected_with_no_effect() -> None:
    clock = FixedClock(NOW + timedelta(seconds=121))
    sim = a_simulator(clock=clock)
    rejection = paid(sim.submit(a_request()))
    assert rejection.status is LedgerStatus.EXPIRED_REJECTED
    assert rejection.effect_recorded is False
    assert sim.effect_count() == 0
    assert sim.rejection_count() == 1


def test_the_rejection_is_durable_so_a_replay_cannot_sneak_in() -> None:
    clock = FixedClock(NOW + timedelta(seconds=121))
    sim = a_simulator(clock=clock)
    first = sim.submit(a_request())
    second = sim.submit(a_request())
    assert second == first
    assert sim.effect_count() == 0


def test_a_record_cannot_claim_a_rejection_that_had_an_effect() -> None:
    with pytest.raises(ValidationError):
        PaymentRecord(
            provider="sim",
            payment_key="a" * 64,
            request_hash="b" * 64,
            seller_id="s",
            amount=Money.paise(1),
            expires_at=EXPIRY,
            status=LedgerStatus.EXPIRED_REJECTED,
            provider_reference="ref",
            effect_recorded=True,
            created_at=NOW,
        )


def test_an_accepted_payment_must_carry_a_reference() -> None:
    with pytest.raises(ValidationError):
        PaymentRecord(
            provider="sim",
            payment_key="a" * 64,
            request_hash="b" * 64,
            seller_id="s",
            amount=Money.paise(1),
            expires_at=EXPIRY,
            status=LedgerStatus.SUCCEEDED,
            provider_reference=None,
            effect_recorded=True,
            created_at=NOW,
        )


# -- the scenario that matters ---------------------------------------------


def test_accept_then_timeout_commits_the_effect_and_then_loses_the_reply() -> None:
    """The exact failure the product exists to survive."""
    sim = a_simulator(Scenario.ACCEPT_THEN_TIMEOUT)
    with pytest.raises(ResponseLost):
        sim.submit(a_request())

    assert sim.effect_count() == 1, "the money moved even though nobody was told"
    found = sim.query(payment_key="a" * 64)
    assert isinstance(found, PaymentRecord)
    assert found.status is LedgerStatus.SUCCEEDED


def test_querying_after_a_lost_response_finds_the_payment() -> None:
    sim = a_simulator(Scenario.ACCEPT_THEN_TIMEOUT)
    with pytest.raises(ResponseLost):
        sim.submit(a_request())
    assert isinstance(sim.query(payment_key="a" * 64), PaymentRecord)


def test_resending_after_a_lost_response_finds_it_instead_of_paying_twice() -> None:
    """The reply is lost once. A resend then recognises the key and answers.

    This is how the ambiguity actually resolves: the task resends the identical
    payload, the provider sees a key it already has, and returns the original
    facts rather than taking a second payment.
    """
    sim = a_simulator(Scenario.ACCEPT_THEN_TIMEOUT)
    with pytest.raises(ResponseLost):
        sim.submit(a_request())

    for _ in range(3):
        resent = sim.submit(a_request())
        assert isinstance(resent, PaymentRecord)
        assert resent.status is LedgerStatus.SUCCEEDED

    assert sim.effect_count() == 1


def test_a_definitive_failure_is_terminal_and_still_one_record() -> None:
    sim = a_simulator(Scenario.DEFINITIVE_FAILURE)
    result = paid(sim.submit(a_request()))
    assert result.status is LedgerStatus.FAILED
    assert sim.effect_count() == 1


def test_the_scenario_is_captured_on_the_record() -> None:
    """Switching scenarios later must not rewrite what already happened."""
    sim = a_simulator(Scenario.SUCCESS)
    first = paid(sim.submit(a_request()))
    sim.set_scenario(Scenario.DEFINITIVE_FAILURE)
    stored = sim.query(payment_key="a" * 64)
    assert isinstance(stored, PaymentRecord)
    assert stored.scenario is Scenario.SUCCESS
    assert stored == first


# -- query -----------------------------------------------------------------


def test_an_unknown_key_is_not_found_rather_than_an_error() -> None:
    assert isinstance(a_simulator().query(payment_key="z" * 64), NotFound)


# -- orders ----------------------------------------------------------------


def an_order(**over: Any) -> OrderRequest:
    base: dict[str, Any] = dict(
        order_key="e" * 64, payment_reference="payref-00000001", quote_hash="c" * 64
    )
    base.update(over)
    return OrderRequest(**base)


def test_order_creation_is_idempotent_on_its_key() -> None:
    sim = a_simulator()
    first = sim.create_order(an_order())
    second = sim.create_order(an_order())
    assert first == second
    assert sim.order_effect_count() == 1


def test_paid_order_missing_returns_not_found_rather_than_raising() -> None:
    """ "We cannot find your order" is a fact to record, not an error to retry."""
    sim = a_simulator(Scenario.PAID_ORDER_MISSING)
    assert isinstance(sim.create_order(an_order()), NotFound)
    assert sim.order_effect_count() == 0


def test_an_order_can_be_read_back() -> None:
    sim = a_simulator()
    created = sim.create_order(an_order())
    assert sim.get_order(order_key="e" * 64) == created


# -- refunds are never initiated here --------------------------------------


def test_the_simulator_exposes_no_way_to_start_a_refund() -> None:
    """ProofPath never initiates a refund; refunds arrive as provider facts."""
    surface = {name for name in dir(Simulator) if not name.startswith("_")}
    for forbidden in ("initiate_refund", "start_refund", "refund", "create_refund"):
        assert forbidden not in surface
    assert "query_refund" in surface


def test_an_unknown_refund_reference_is_not_found() -> None:
    assert isinstance(a_simulator().query_refund(refund_reference="none"), NotFound)
