"""The consent copy contract (WP-08, WP-09).

These strings are load-bearing, so they are asserted rather than left to whoever
writes the component. The simulation disclaimer is the difference between an
honest demo and a misleading one; "we're confirming this payment" instead of
"payment failed" is the difference between a shopper who waits and one who pays
twice.
"""

from __future__ import annotations

import pytest

from services.application.copy import (
    APPROVE_CEILING_LABEL,
    APPROVE_LABEL,
    ESTIMATED_FEES_NOTE,
    FIXTURE_LABEL,
    JOB_FAILED,
    SIMULATION_DISCLAIMER,
    BlockedCopy,
    OrderCopy,
    PaymentCopy,
    approve_label,
    lower_bound_label,
)
from services.domain.money import Confidence
from services.domain.transitions import OrderState, PaymentState


def test_the_simulation_disclaimer_says_all_three_things() -> None:
    """Simulated, no money, no retailer order. Dropping any one misleads."""
    assert "Simulated checkout" in SIMULATION_DISCLAIMER
    assert "no money moved" in SIMULATION_DISCLAIMER
    assert "no retailer order placed" in SIMULATION_DISCLAIMER


def test_the_fixture_label_says_the_prices_are_not_real() -> None:
    assert "Demonstration data" in FIXTURE_LABEL
    assert "not current retailer offers" in FIXTURE_LABEL


def test_the_approve_label_names_the_exact_amount() -> None:
    assert approve_label(60_500, Confidence.VERIFIED) == "Approve simulated ₹605.00"
    assert approve_label(59_000, Confidence.VERIFIED) == "Approve simulated ₹590.00"
    assert approve_label(1, Confidence.VERIFIED) == "Approve simulated ₹0.01"


def test_an_estimated_label_says_up_to() -> None:
    """The words "up to" are the whole difference between a bound and a claim."""
    assert approve_label(59_000, Confidence.ESTIMATED) == "Approve simulated up to ₹590.00"


def test_a_verified_label_does_not_say_up_to() -> None:
    """The inverse guard: relabelling everything "up to" would be its own lie."""
    assert "up to" not in approve_label(59_000, Confidence.VERIFIED)


def test_an_unknown_total_has_no_approve_label_at_all() -> None:
    """No ceiling, no maximum to authorise, so no wording is honest."""
    with pytest.raises(ValueError):
        approve_label(59_000, Confidence.UNKNOWN)


def test_the_ceiling_template_says_both_simulated_and_up_to() -> None:
    """Both words carry weight: one bounds the money, the other bounds the claim."""
    assert "simulated" in APPROVE_CEILING_LABEL.lower()
    assert "up to" in APPROVE_CEILING_LABEL.lower()


def test_the_approve_label_template_says_simulated() -> None:
    """A control that just said 'Approve' would be a different promise."""
    assert "simulated" in APPROVE_LABEL.lower()


def test_an_unknown_payment_is_phrased_as_neither_outcome() -> None:
    wording = PaymentCopy.UNKNOWN.value.lower()
    assert "fail" not in wording
    assert "success" not in wording and "confirmed" not in wording
    assert "confirming" in wording


def test_every_payment_state_has_wording() -> None:
    for state in PaymentState:
        assert PaymentCopy[state.name].value


def test_every_order_state_has_wording() -> None:
    for state in OrderState:
        assert OrderCopy[state.name].value


def test_payment_and_order_wording_are_never_the_same_sentence() -> None:
    """They are three separate facts and must never read as one."""
    assert set(c.value for c in PaymentCopy) & set(c.value for c in OrderCopy) == set()


def test_a_failed_job_says_the_payment_is_unaffected() -> None:
    assert "payment is unaffected" in JOB_FAILED.lower()
    assert "payment failed" not in JOB_FAILED.lower()


def test_an_unknown_total_is_shown_as_a_lower_bound_never_a_total() -> None:
    assert lower_bound_label(58_000) == "At least ₹580.00"
    assert "At least" in lower_bound_label(1)


def test_the_blocked_wording_covers_every_refusal_a_shopper_can_hit() -> None:
    expected = {
        "EXPOSURE",
        "QUOTE_EXPIRED",
        "PREPARATION_STALE",
        "UNKNOWN_FEE",
        "UNPRICED_LINE",
        "PACK_CHANGED",
        "CANCELLED",
        "PAID_NO_ORDER",
    }
    assert expected <= {member.name for member in BlockedCopy}


def test_the_exposure_message_does_not_invite_a_second_attempt() -> None:
    wording = BlockedCopy.EXPOSURE.value.lower()
    assert "try again" not in wording
    assert "confirming" in wording


def test_the_estimated_fees_note_says_where_the_fees_came_from() -> None:
    """WP-02-A1 s6: mode and fixture labels do not cover an estimated fee.

    A live quote is live data and can still carry a fee estimated from a
    published schedule rather than read from the cart. Without this the shopper
    approves "up to" a bound with nothing telling them it is a bound, or where
    the number came from.
    """
    assert "estimated" in ESTIMATED_FEES_NOTE.lower()
    assert "published" in ESTIMATED_FEES_NOTE.lower()


def test_the_note_does_not_promise_a_guarantee_it_cannot_keep() -> None:
    """The ceiling is best-effort, and the wording has to admit that.

    WP-02-A1 s6 records two ways it can be beaten: an unmodelled late-night
    surcharge, and schedules drifting with no staleness signal. "will not
    exceed" would be a promise; "should not exceed" is the truth.
    """
    assert "should not exceed" in ESTIMATED_FEES_NOTE
    assert "will not exceed" not in ESTIMATED_FEES_NOTE
    assert "guarantee" not in ESTIMATED_FEES_NOTE.lower()
