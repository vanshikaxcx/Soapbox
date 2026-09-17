"""Money, charges, totals and budget (WP-02 acceptance criteria 2, 3, 4)."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from services.domain.errors import BudgetExceeded
from services.domain.money import (
    Amount,
    BudgetCheck,
    Charge,
    ChargeKind,
    Confidence,
    Money,
    Totals,
    check_budget,
    compute_totals,
    difference,
    total_of,
    unit_rate,
    worst,
)
from services.domain.units import Quantity, Unit

# -- integer paise only ----------------------------------------------------


@pytest.mark.parametrize("bad", [1.0, 0.1, "100", Decimal("1.00"), True])
def test_money_rejects_anything_that_is_not_an_int(bad: object) -> None:
    with pytest.raises(ValidationError):
        Money(amount_paise=bad)  # type: ignore[arg-type]


def test_money_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        Money(amount_paise=-1)


def test_money_has_no_division_operator() -> None:
    # Division is how exact arithmetic quietly becomes approximate arithmetic.
    assert not hasattr(Money.paise(100), "__truediv__")
    assert not hasattr(Money, "divide")


def test_money_multiplication_requires_whole_non_negative_factor() -> None:
    assert Money.paise(150).times(3) == Money.paise(450)
    for bad in (1.5, -1, True):
        with pytest.raises(TypeError):
            Money.paise(150).times(bad)  # type: ignore[arg-type]


def test_subtraction_cannot_go_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        Money.paise(100).subtract(Money.paise(101))
    assert difference(Money.paise(100), Money.paise(101)).amount_paise == -1


# -- unknown fees are never zero -------------------------------------------


def test_unknown_amount_has_no_value_and_a_value_is_never_unknown() -> None:
    assert Amount.unknown().amount is None
    with pytest.raises(ValidationError):
        Amount(amount=Money.paise(0), confidence=Confidence.UNKNOWN)
    with pytest.raises(ValidationError):
        Amount(amount=None, confidence=Confidence.VERIFIED)


def test_an_unknown_charge_cannot_be_built_with_a_zero_amount() -> None:
    charge = Charge.unknown_charge(ChargeKind.DELIVERY)
    assert charge.amount is None
    assert charge.confidence is Confidence.UNKNOWN
    with pytest.raises(ValueError, match="UNKNOWN"):
        Charge.known_charge(ChargeKind.DELIVERY, Money.paise(0), Confidence.UNKNOWN)


# -- totals ----------------------------------------------------------------


def _line(paise: int, confidence: Confidence = Confidence.VERIFIED) -> Amount:
    return Amount.known(Money.paise(paise), confidence)


def test_all_verified_gives_a_complete_total() -> None:
    totals = compute_totals(
        [_line(10_000), _line(5_000)],
        [Charge.known_charge(ChargeKind.DELIVERY, Money.paise(2_000))],
    )
    assert totals.confidence is Confidence.VERIFIED
    assert totals.total == Money.paise(17_000)
    assert totals.unknown_charges == ()


def test_one_estimated_charge_makes_the_whole_total_estimated() -> None:
    totals = compute_totals(
        [_line(10_000)],
        [Charge.known_charge(ChargeKind.SURGE, Money.paise(500), Confidence.ESTIMATED)],
    )
    assert totals.confidence is Confidence.ESTIMATED
    assert totals.total == Money.paise(10_500)


def test_one_unknown_charge_makes_the_total_unknown_and_never_zero() -> None:
    totals = compute_totals(
        [_line(10_000)],
        [Charge.unknown_charge(ChargeKind.DELIVERY)],
    )
    assert totals.confidence is Confidence.UNKNOWN
    assert totals.total is None
    assert totals.known_subtotal == Money.paise(10_000)
    assert totals.unknown_charges == (ChargeKind.DELIVERY,)


def test_an_unknown_line_also_makes_the_total_unknown() -> None:
    totals = compute_totals([_line(10_000), Amount.unknown()], [])
    assert totals.total is None
    assert totals.known_subtotal == Money.paise(10_000)
    assert totals.unpriced_lines == 1


def test_an_unpriced_line_is_never_reported_as_a_phantom_fee() -> None:
    """The review caught this: an unpriced ITEM was being named as an unknown
    "other" CHARGE, so the UI would have told the shopper we could not confirm a
    fee when the truth is we could not price an item."""
    totals = compute_totals([Amount.unknown()], [])
    assert totals.unknown_charges == ()
    assert totals.unpriced_lines == 1


def test_an_unknown_charge_and_an_unpriced_line_are_reported_separately() -> None:
    totals = compute_totals(
        [_line(10_000), Amount.unknown()],
        [Charge.unknown_charge(ChargeKind.DELIVERY)],
    )
    assert totals.unknown_charges == (ChargeKind.DELIVERY,)
    assert totals.unpriced_lines == 1


def test_a_known_total_cannot_carry_unknowns() -> None:
    with pytest.raises(ValidationError):
        Totals(
            known_subtotal=Money.paise(1),
            floor=Money.paise(1),
            total=Money.paise(1),
            confidence=Confidence.VERIFIED,
            unknown_charges=(),
            unpriced_lines=2,
        )


def test_totals_record_rejects_an_inconsistent_shape() -> None:
    with pytest.raises(ValidationError):
        Totals(
            known_subtotal=Money.paise(1),
            floor=Money.paise(1),
            total=Money.paise(1),
            confidence=Confidence.UNKNOWN,
            unknown_charges=(ChargeKind.DELIVERY,),
        )
    with pytest.raises(ValidationError):
        Totals(
            known_subtotal=Money.paise(1),
            floor=Money.paise(1),
            total=None,
            confidence=Confidence.VERIFIED,
            unknown_charges=(),
        )


@pytest.mark.parametrize(
    ("given_confidences", "expected"),
    [
        ([], Confidence.VERIFIED),
        ([Confidence.VERIFIED], Confidence.VERIFIED),
        ([Confidence.VERIFIED, Confidence.ESTIMATED], Confidence.ESTIMATED),
        ([Confidence.ESTIMATED, Confidence.UNKNOWN], Confidence.UNKNOWN),
        ([Confidence.UNKNOWN, Confidence.VERIFIED], Confidence.UNKNOWN),
    ],
)
def test_worst_confidence_wins(given_confidences: list[Confidence], expected: Confidence) -> None:
    assert worst(given_confidences) is expected


# -- budget ----------------------------------------------------------------


def test_budget_equality_is_within_and_one_paise_over_is_not() -> None:
    totals = compute_totals([_line(90_000)], [])
    assert check_budget(totals, 90_000) is BudgetCheck.WITHIN
    exceeded = check_budget(totals, 89_999)
    assert isinstance(exceeded, BudgetExceeded)
    assert exceeded.total_paise == 90_000


def test_an_unknown_total_is_never_reported_as_within_budget() -> None:
    totals = compute_totals([_line(10)], [Charge.unknown_charge(ChargeKind.DELIVERY)])
    assert check_budget(totals, 90_000) is BudgetCheck.UNKNOWN


# -- unit rates are exact and are not money --------------------------------


def test_unit_rate_is_an_exact_fraction_not_a_float_or_money() -> None:
    rate = unit_rate(Money.paise(10_000), Quantity.of(3, Unit.KG), per_base_units=100)
    assert isinstance(rate, Fraction)
    assert rate == Fraction(10_000 * 100, 3_000)
    assert not isinstance(rate, float)


def test_unit_rate_rounding_never_leaks_into_a_total() -> None:
    # Three lines whose per-unit rates do not divide evenly. The total is still
    # the exact sum of the line amounts, not a rebuilt figure from the rates.
    lines = [_line(3_333), _line(3_333), _line(3_334)]
    assert compute_totals(lines, []).total == Money.paise(10_000)


# -- properties ------------------------------------------------------------


@given(st.lists(st.integers(min_value=0, max_value=10**9), max_size=20))
def test_known_subtotal_is_always_a_lower_bound(paise: list[int]) -> None:
    lines = [_line(p) for p in paise]
    totals = compute_totals(lines, [Charge.unknown_charge(ChargeKind.DELIVERY)])
    assert totals.total is None
    assert totals.known_subtotal.amount_paise == sum(paise)


@given(st.lists(st.integers(min_value=0, max_value=10**9), min_size=1, max_size=20))
def test_totals_never_go_negative_and_match_their_sum(paise: list[int]) -> None:
    totals = compute_totals([_line(p) for p in paise], [])
    assert totals.total is not None
    assert totals.total.amount_paise == sum(paise) >= 0


@given(st.lists(st.integers(min_value=0, max_value=10**6), max_size=10))
def test_total_of_is_order_independent(paise: list[int]) -> None:
    forward = total_of([Money.paise(p) for p in paise])
    backward = total_of([Money.paise(p) for p in reversed(paise)])
    assert forward == backward
