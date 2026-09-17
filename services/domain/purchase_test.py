"""Freshness, quote construction and exposure (WP-02 criteria 6, 8, 11, 12, 13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.domain.errors import (
    AttemptBlockedByExposure,
    DiffNotAccepted,
    PreparationExpired,
    QuoteExpired,
    QuoteNotConstructible,
)
from services.domain.money import Amount, Charge, ChargeKind, Confidence, Money, compute_totals
from services.domain.purchase import (
    AttemptSnapshot,
    Preparation,
    PurchaseSnapshot,
    can_build_quote,
    check_quote_live,
    has_unresolved_exposure,
    is_fresh,
    may_create_attempt,
    quote_window,
)
from services.domain.transitions import DispatchState, PaymentState

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def preparation(
    *, refreshed_at: datetime = NOW, changes: int = 0, accepted: bool = False
) -> Preparation:
    diff_hash = "d" * 64
    return Preparation(
        preparation_id="prep-0001",
        purchase_id="purchase-001",
        refreshed_at=refreshed_at,
        diff_hash=diff_hash,
        change_count=changes,
        accepted_diff_hash=diff_hash if accepted else None,
    )


VERIFIED_TOTALS = compute_totals([Amount.known(Money.paise(90_000))], [])
ESTIMATED_TOTALS = compute_totals(
    [Amount.known(Money.paise(90_000))],
    [Charge.known_charge(ChargeKind.SURGE, Money.paise(500), Confidence.ESTIMATED)],
)
UNKNOWN_TOTALS = compute_totals(
    [Amount.known(Money.paise(90_000))], [Charge.unknown_charge(ChargeKind.DELIVERY)]
)


# -- freshness boundaries --------------------------------------------------


@pytest.mark.parametrize(
    ("elapsed", "expected_fresh"),
    [(0, True), (119, True), (120, False), (121, False)],
)
def test_preparation_freshness_boundary_is_exactly_120_seconds(
    elapsed: int, expected_fresh: bool
) -> None:
    prep = preparation(refreshed_at=NOW)
    assert is_fresh(prep, NOW + timedelta(seconds=elapsed)) is expected_fresh


@pytest.mark.parametrize(
    ("elapsed", "expected_live"),
    [(0, True), (119, True), (120, False), (121, False)],
)
def test_quote_lifetime_boundary_is_exactly_120_seconds(
    elapsed: int, expected_live: bool
) -> None:
    window = quote_window(NOW)
    result = check_quote_live("quote-001", window, NOW + timedelta(seconds=elapsed))
    assert (result is None) is expected_live
    if not expected_live:
        assert isinstance(result, QuoteExpired)


# -- quote construction ----------------------------------------------------


def test_an_unchanged_fresh_preparation_yields_a_quote() -> None:
    assert can_build_quote(preparation(changes=0), VERIFIED_TOTALS, NOW) is None


def test_a_changed_preparation_needs_acceptance_first() -> None:
    """The dedicated error, not an overloaded QuoteNotConstructible reason."""
    result = can_build_quote(preparation(changes=3), VERIFIED_TOTALS, NOW)
    assert isinstance(result, DiffNotAccepted)
    assert result.preparation_id == "prep-0001"


def test_an_unpriced_line_and_an_unknown_fee_give_different_reasons() -> None:
    unpriced = compute_totals([Amount.unknown()], [])
    result = can_build_quote(preparation(), unpriced, NOW)
    assert isinstance(result, QuoteNotConstructible)
    assert result.reason == "unpriced_line"


def test_an_accepted_fresh_preparation_yields_a_quote_without_refreshing_again() -> None:
    """The anti-loop rule: acceptance plus freshness is sufficient."""
    accepted = preparation(changes=3, accepted=True)
    assert can_build_quote(accepted, VERIFIED_TOTALS, NOW + timedelta(seconds=119)) is None


def test_the_accept_then_quote_loop_terminates() -> None:
    """Run the whole sequence repeatedly; it must never re-enter refresh."""
    accepted = preparation(changes=2, accepted=True)
    for second in range(0, 119):
        assert can_build_quote(accepted, VERIFIED_TOTALS, NOW + timedelta(seconds=second)) is None


def test_a_stale_preparation_cannot_yield_a_quote_however_accepted() -> None:
    accepted = preparation(changes=1, accepted=True)
    result = can_build_quote(accepted, VERIFIED_TOTALS, NOW + timedelta(seconds=121))
    assert isinstance(result, PreparationExpired)


def test_an_unknown_charge_blocks_the_quote_and_names_the_charge() -> None:
    result = can_build_quote(preparation(), UNKNOWN_TOTALS, NOW)
    assert isinstance(result, QuoteNotConstructible)
    assert result.reason == "unknown_charge"
    assert "delivery" in result.charge_kinds


def test_an_estimated_total_is_approvable_as_a_ceiling() -> None:
    """WP-02-A1: estimated charges are carried at their upper bound.

    UNKNOWN still blocks, one test above -- that case has no ceiling at all.
    """
    assert can_build_quote(preparation(), ESTIMATED_TOTALS, NOW) is None


# -- exposure --------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        PaymentState.CLAIMED,
        PaymentState.PENDING,
        PaymentState.UNKNOWN,
        PaymentState.SUCCEEDED,
    ],
)
def test_a_started_dispatch_with_a_live_payment_is_exposure(state: PaymentState) -> None:
    attempt = AttemptSnapshot(
        attempt_id="attempt-01", dispatch=DispatchState.STARTED, payment=state
    )
    assert has_unresolved_exposure(attempt) is True


def test_a_definitively_failed_payment_is_not_exposure() -> None:
    attempt = AttemptSnapshot(
        attempt_id="attempt-01", dispatch=DispatchState.STARTED, payment=PaymentState.FAILED
    )
    assert has_unresolved_exposure(attempt) is False


@pytest.mark.parametrize(
    "dispatch", [DispatchState.READY, DispatchState.EXPIRED_UNSENT]
)
def test_no_provider_call_means_no_exposure(dispatch: DispatchState) -> None:
    attempt = AttemptSnapshot(
        attempt_id="attempt-01", dispatch=dispatch, payment=PaymentState.CLAIMED
    )
    assert has_unresolved_exposure(attempt) is False


# -- attempt creation ------------------------------------------------------


def test_a_first_attempt_is_permitted() -> None:
    assert may_create_attempt(PurchaseSnapshot()) is None


def test_an_active_attempt_blocks_a_new_one() -> None:
    active = AttemptSnapshot(
        attempt_id="attempt-01", dispatch=DispatchState.READY, payment=PaymentState.CLAIMED
    )
    result = may_create_attempt(PurchaseSnapshot(active_attempt=active))
    assert isinstance(result, AttemptBlockedByExposure)


@pytest.mark.parametrize(
    "state", [PaymentState.PENDING, PaymentState.UNKNOWN, PaymentState.SUCCEEDED]
)
def test_an_unresolved_or_paid_previous_attempt_blocks_a_replacement(
    state: PaymentState,
) -> None:
    """Succeeded blocks too: the purchase is paid, a retry would pay twice."""
    previous = AttemptSnapshot(
        attempt_id="attempt-01", dispatch=DispatchState.STARTED, payment=state
    )
    result = may_create_attempt(PurchaseSnapshot(last_attempt=previous))
    assert isinstance(result, AttemptBlockedByExposure)
    assert result.payment_state == str(state)


def test_a_definitively_failed_previous_attempt_permits_a_new_one() -> None:
    previous = AttemptSnapshot(
        attempt_id="attempt-01", dispatch=DispatchState.STARTED, payment=PaymentState.FAILED
    )
    assert may_create_attempt(PurchaseSnapshot(last_attempt=previous)) is None


def test_an_expired_unsent_attempt_permits_a_new_one() -> None:
    """Nothing was ever sent, so there is nothing to be exposed to."""
    previous = AttemptSnapshot(
        attempt_id="attempt-01",
        dispatch=DispatchState.EXPIRED_UNSENT,
        payment=PaymentState.NOT_STARTED,
    )
    assert may_create_attempt(PurchaseSnapshot(last_attempt=previous)) is None


def test_a_failed_job_is_not_represented_here_at_all() -> None:
    """Job state cannot reach this decision, so it cannot unblock a payment.

    The absence is the assertion: AttemptSnapshot has no job field.
    """
    assert "job" not in AttemptSnapshot.model_fields
    assert "job" not in PurchaseSnapshot.model_fields
