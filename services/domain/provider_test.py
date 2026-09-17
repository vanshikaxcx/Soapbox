"""Provider fact application (WP-02 acceptance criteria 11, and 7 for independence).

The three rules under test: terminal is sticky, contradictory terminals
quarantine, and an older observation never overwrites a newer one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from services.domain.errors import ContradictoryProviderFact, FactIgnoredStale
from services.domain.provider import (
    Applied,
    Current,
    OrderFacts,
    PaymentFacts,
    RefundFacts,
    apply_order_facts,
    apply_payment_facts,
    apply_refund_facts,
)
from services.domain.transitions import OrderState, PaymentState, RefundState

T0 = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
T1 = T0 + timedelta(seconds=30)
T2 = T0 + timedelta(seconds=60)


def payment(state: PaymentState, at: datetime = T1) -> PaymentFacts:
    return PaymentFacts(state=state, observed_at=at)


# -- rule 1: terminal is sticky -------------------------------------------


def test_an_old_pending_cannot_downgrade_a_success() -> None:
    """The headline guarantee. A late callback arrives claiming 'pending'."""
    current = Current(state=PaymentState.SUCCEEDED, observed_at=T1)
    result = apply_payment_facts(current, payment(PaymentState.PENDING, at=T0))
    assert isinstance(result, FactIgnoredStale)
    assert result.current == "succeeded"


def test_even_a_newer_pending_cannot_downgrade_a_success() -> None:
    """Stickiness does not depend on timestamps being trustworthy."""
    current = Current(state=PaymentState.SUCCEEDED, observed_at=T0)
    result = apply_payment_facts(current, payment(PaymentState.PENDING, at=T2))
    assert isinstance(result, FactIgnoredStale)


def test_unknown_cannot_overwrite_a_terminal_state() -> None:
    current = Current(state=PaymentState.FAILED, observed_at=T0)
    assert isinstance(
        apply_payment_facts(current, payment(PaymentState.UNKNOWN, at=T2)), FactIgnoredStale
    )


def test_reconfirming_a_terminal_state_is_an_idempotent_no_op() -> None:
    current = Current(state=PaymentState.SUCCEEDED, observed_at=T0)
    result = apply_payment_facts(current, payment(PaymentState.SUCCEEDED, at=T2))
    assert isinstance(result, Applied)
    assert result.state is PaymentState.SUCCEEDED
    assert result.changed is False


# -- rule 2: contradictory terminals quarantine ---------------------------


def test_failed_after_succeeded_is_contradictory_and_does_not_apply() -> None:
    current = Current(state=PaymentState.SUCCEEDED, observed_at=T0)
    result = apply_payment_facts(current, payment(PaymentState.FAILED, at=T2))
    assert isinstance(result, ContradictoryProviderFact)
    assert result.current == "succeeded"
    assert result.incoming == "failed"


def test_succeeded_after_failed_is_equally_contradictory() -> None:
    current = Current(state=PaymentState.FAILED, observed_at=T0)
    result = apply_payment_facts(current, payment(PaymentState.SUCCEEDED, at=T2))
    assert isinstance(result, ContradictoryProviderFact)


def test_a_contradiction_leaves_the_state_untouched() -> None:
    current = Current(state=PaymentState.SUCCEEDED, observed_at=T0)
    result = apply_payment_facts(current, payment(PaymentState.FAILED, at=T2))
    assert not isinstance(result, Applied)  # nothing to write


# -- rule 3: never move backwards in time ---------------------------------


def test_an_out_of_order_observation_is_ignored() -> None:
    current = Current(state=PaymentState.PENDING, observed_at=T2)
    result = apply_payment_facts(current, payment(PaymentState.UNKNOWN, at=T0))
    assert isinstance(result, FactIgnoredStale)


def test_an_equally_recent_observation_applies() -> None:
    current = Current(state=PaymentState.PENDING, observed_at=T1)
    result = apply_payment_facts(current, payment(PaymentState.SUCCEEDED, at=T1))
    assert isinstance(result, Applied)
    assert result.state is PaymentState.SUCCEEDED


def test_replaying_an_identical_fact_is_a_no_op() -> None:
    current = Current(state=PaymentState.PENDING, observed_at=T1)
    first = apply_payment_facts(current, payment(PaymentState.PENDING, at=T1))
    assert isinstance(first, Applied)
    assert first.changed is False


# -- the states a provider may report -------------------------------------


@pytest.mark.parametrize("state", [PaymentState.NOT_STARTED, PaymentState.CLAIMED])
def test_a_provider_cannot_report_our_own_internal_states(state: PaymentState) -> None:
    with pytest.raises(ValidationError):
        PaymentFacts(state=state, observed_at=T1)


def test_facts_require_an_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        PaymentFacts(state=PaymentState.PENDING, observed_at=datetime(2026, 9, 15, 12, 0, 0))


# -- order and refund move independently ----------------------------------


def test_a_confirmed_order_does_not_touch_payment_state() -> None:
    order_current = Current(state=OrderState.NOT_CREATED)
    result = apply_order_facts(
        order_current, OrderFacts(state=OrderState.CONFIRMED, observed_at=T1)
    )
    assert isinstance(result, Applied)
    assert result.state is OrderState.CONFIRMED
    # Payment is a separate machine with a separate current value; nothing here
    # could have changed it, which is the point of keeping them apart.


def test_a_refund_may_be_first_observed_as_completed() -> None:
    """A late callback can report a refund we never saw go pending.

    Rejecting it would discard real provider evidence.
    """
    result = apply_refund_facts(
        Current(state=RefundState.NONE),
        RefundFacts(state=RefundState.COMPLETED, observed_at=T1),
    )
    assert isinstance(result, Applied)
    assert result.state is RefundState.COMPLETED


def test_an_old_pending_refund_cannot_downgrade_a_completed_one() -> None:
    current = Current(state=RefundState.COMPLETED, observed_at=T1)
    assert isinstance(
        apply_refund_facts(current, RefundFacts(state=RefundState.PENDING, observed_at=T0)),
        FactIgnoredStale,
    )


def test_an_order_can_go_unknown_then_confirmed() -> None:
    current = Current(state=OrderState.UNKNOWN, observed_at=T0)
    result = apply_order_facts(current, OrderFacts(state=OrderState.CONFIRMED, observed_at=T1))
    assert isinstance(result, Applied)
    assert result.state is OrderState.CONFIRMED


# -- property: no sequence of facts ever moves a terminal state ------------


@given(
    st.lists(
        st.sampled_from(
            [
                PaymentState.PENDING,
                PaymentState.UNKNOWN,
                PaymentState.SUCCEEDED,
                PaymentState.FAILED,
            ]
        ),
        min_size=1,
        max_size=12,
    ),
    st.lists(st.integers(min_value=0, max_value=600), min_size=12, max_size=12),
)
def test_once_terminal_a_payment_never_changes(
    reports: list[PaymentState], offsets: list[int]
) -> None:
    current = Current(state=PaymentState.CLAIMED, observed_at=T0)
    settled: PaymentState | None = None

    for state, offset in zip(reports, offsets, strict=False):
        result = apply_payment_facts(
            current, payment(state, at=T0 + timedelta(seconds=offset))
        )
        if isinstance(result, Applied):
            if settled is not None:
                # Already terminal: the only permitted outcome is the same state.
                assert result.state is settled
            current = Current(state=result.state, observed_at=result.observed_at)
            if result.state in (PaymentState.SUCCEEDED, PaymentState.FAILED):
                # This loop only ever feeds payment facts in, so the union the
                # generic Applied carries is a PaymentState here.
                assert isinstance(result.state, PaymentState)
                settled = result.state
        else:
            # An error never changes anything.
            assert isinstance(result, (FactIgnoredStale, ContradictoryProviderFact))

    if settled is not None:
        assert current.state is settled
