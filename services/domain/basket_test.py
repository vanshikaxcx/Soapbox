"""Basket comparison (WP-02 acceptance criterion 7).

The rule being defended: an estimated or unknown basket is never declared
cheaper than a verified one, even when its headline number looks lower.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from services.domain.basket import BasketCost, Comparison, cheapest, compare_baskets
from services.domain.errors import MixedModeComparison
from services.domain.ids import Mode
from services.domain.money import (
    Amount,
    Charge,
    ChargeKind,
    Confidence,
    Money,
    compute_totals,
)


def verified(paise: int, *, mode: Mode = Mode.LIVE, basket_id: str = "b1") -> BasketCost:
    return BasketCost(
        basket_id=basket_id,
        mode=mode,
        totals=compute_totals([Amount.known(Money.paise(paise))], []),
    )


def estimated(paise: int, fee: int, *, basket_id: str = "b2") -> BasketCost:
    return BasketCost(
        basket_id=basket_id,
        mode=Mode.LIVE,
        totals=compute_totals(
            [Amount.known(Money.paise(paise))],
            [Charge.known_charge(ChargeKind.SURGE, Money.paise(fee), Confidence.ESTIMATED)],
        ),
    )


def unknown(paise: int, *, basket_id: str = "b3") -> BasketCost:
    return BasketCost(
        basket_id=basket_id,
        mode=Mode.LIVE,
        totals=compute_totals(
            [Amount.known(Money.paise(paise))],
            [Charge.unknown_charge(ChargeKind.DELIVERY)],
        ),
    )


# -- both exact ------------------------------------------------------------


def test_two_verified_baskets_compare_on_their_totals() -> None:
    assert compare_baskets(verified(10_000), verified(12_000)) is Comparison.LEFT_CHEAPER
    assert compare_baskets(verified(12_000), verified(10_000)) is Comparison.RIGHT_CHEAPER
    assert compare_baskets(verified(10_000), verified(10_000)) is Comparison.EQUAL


# -- the honesty rule ------------------------------------------------------


def test_an_estimated_ceiling_under_a_verified_total_is_proof() -> None:
    """At most 10,500 really is less than exactly 20,000 (WP-02-A1).

    This reverses the pre-A1 rule, which refused the comparison outright. The
    refusal was not caution, it was discarding a fact: an estimated charge is
    carried at its upper bound, so the basket cannot cost more than 10,500 and
    the rival cannot cost less than 20,000.
    """
    cheap_estimate = estimated(10_000, 500)  # ceiling 10,500, floor 10,000
    expensive_verified = verified(20_000)
    assert compare_baskets(cheap_estimate, expensive_verified) is Comparison.LEFT_CHEAPER
    assert compare_baskets(expensive_verified, cheap_estimate) is Comparison.RIGHT_CHEAPER


def test_a_verified_basket_can_be_proven_cheaper_than_an_estimated_one() -> None:
    """Beating the other's known subtotal is proof: its true total is at least that."""
    assert compare_baskets(verified(9_000), estimated(10_000, 500)) is Comparison.LEFT_CHEAPER


def test_a_verified_basket_below_an_unknown_baskets_subtotal_wins() -> None:
    assert compare_baskets(verified(9_000), unknown(10_000)) is Comparison.LEFT_CHEAPER


def test_an_unknown_basket_is_never_cheaper_than_anything() -> None:
    assert compare_baskets(unknown(1), verified(1_000_000)) is Comparison.NOT_COMPARABLE
    assert compare_baskets(unknown(1), estimated(1_000_000, 1)) is Comparison.NOT_COMPARABLE
    assert compare_baskets(unknown(1), unknown(2)) is Comparison.NOT_COMPARABLE


def test_two_estimated_baskets_compare_when_their_bands_are_disjoint() -> None:
    """The headline case: two live merchants, both with estimated fees.

    Pre-A1 this returned NOT_COMPARABLE at every price gap, which meant a live
    two-merchant comparison could never name a winner -- the product's headline
    feature returning "we cannot tell" by construction.
    """
    # ceiling 10,100 vs floor 20,000: no overlap, so the answer is provable.
    assert compare_baskets(estimated(10_000, 100), estimated(20_000, 100)) is (
        Comparison.LEFT_CHEAPER
    )


def test_two_estimated_baskets_do_not_compare_when_their_bands_overlap() -> None:
    """The guard on the test above: overlap still refuses to answer."""
    # ceiling 10,600 vs floor 10,000 -- the true totals could fall either way.
    assert compare_baskets(estimated(10_000, 600), estimated(10_000, 600)) is (
        Comparison.NOT_COMPARABLE
    )


def test_an_estimate_can_beat_a_verified_total_it_sits_entirely_below() -> None:
    """11,000 exactly, against a basket that cannot exceed 10,500."""
    assert compare_baskets(verified(11_000), estimated(10_000, 500)) is (
        Comparison.RIGHT_CHEAPER
    )


# -- modes never mix -------------------------------------------------------


def test_live_and_fixture_baskets_are_never_ranked_together() -> None:
    result = compare_baskets(verified(9_000), verified(10_000, mode=Mode.FIXTURE))
    assert isinstance(result, MixedModeComparison)


def test_cheapest_refuses_a_mixed_mode_list() -> None:
    result = cheapest(
        [verified(9_000, basket_id="a"), verified(10_000, mode=Mode.FIXTURE, basket_id="b")]
    )
    assert isinstance(result, MixedModeComparison)


# -- cheapest --------------------------------------------------------------


def test_cheapest_picks_the_one_that_beats_everything() -> None:
    winner = cheapest(
        [
            verified(9_000, basket_id="a"),
            verified(10_000, basket_id="b"),
            verified(11_000, basket_id="c"),
        ]
    )
    assert winner is not None and not isinstance(winner, MixedModeComparison)
    assert winner.basket_id == "a"


def test_cheapest_can_name_an_estimate_that_sits_below_an_unknown_floor() -> None:
    """At most 9,100 beats at least 10,000, even though neither total is exact."""
    winner = cheapest([estimated(9_000, 100), unknown(10_000)])
    assert winner is not None and not isinstance(winner, MixedModeComparison)
    assert winner.basket_id == "b2"


def test_cheapest_returns_none_when_nothing_can_be_proven() -> None:
    """"We cannot honestly call any of these cheapest" is still a real answer."""
    # Overlapping bands: the unknown basket's floor sits under the estimate's
    # ceiling, so neither can be ruled out.
    assert cheapest([estimated(9_000, 1_500), unknown(10_000)]) is None


def test_cheapest_returns_none_on_a_tie() -> None:
    assert cheapest([verified(9_000, basket_id="a"), verified(9_000, basket_id="b")]) is None


def test_cheapest_of_an_empty_list_is_none() -> None:
    assert cheapest([]) is None


# -- properties ------------------------------------------------------------


@given(
    st.integers(min_value=0, max_value=10**7),
    st.integers(min_value=0, max_value=10**7),
)
def test_comparison_is_antisymmetric(left: int, right: int) -> None:
    forward = compare_baskets(verified(left), verified(right))
    backward = compare_baskets(verified(right), verified(left))
    mirror = {
        Comparison.LEFT_CHEAPER: Comparison.RIGHT_CHEAPER,
        Comparison.RIGHT_CHEAPER: Comparison.LEFT_CHEAPER,
        Comparison.EQUAL: Comparison.EQUAL,
        Comparison.NOT_COMPARABLE: Comparison.NOT_COMPARABLE,
    }
    assert isinstance(forward, Comparison) and isinstance(backward, Comparison)
    assert mirror[forward] is backward


@given(
    st.integers(min_value=0, max_value=10**7),
    st.integers(min_value=0, max_value=10**7),
    st.integers(min_value=0, max_value=10**6),
)
def test_a_win_is_always_backed_by_a_disjoint_band(
    exact: int, other: int, fee: int
) -> None:
    """The soundness property that replaces the pre-A1 "inexact never wins" rule.

    A1 lets an estimate win, so the invariant worth defending is no longer *who*
    may win but *what a win means*: the winner's ceiling must sit strictly below
    the loser's floor. Anything else would be a guess dressed as a verdict.
    """
    for inexact in (estimated(other, fee), unknown(other)):
        left, right = inexact, verified(exact)
        verdict = compare_baskets(left, right)
        if verdict is Comparison.LEFT_CHEAPER:
            assert left.totals.total is not None
            assert left.totals.total.amount_paise < right.totals.floor.amount_paise
        if verdict is Comparison.RIGHT_CHEAPER:
            assert right.totals.total is not None
            assert right.totals.total.amount_paise < left.totals.floor.amount_paise


@given(
    st.integers(min_value=0, max_value=10**7),
    st.integers(min_value=0, max_value=10**6),
)
def test_an_unknown_basket_never_wins(paise: int, fee: int) -> None:
    """No ceiling means no proof, at any price. This survives A1 unchanged."""
    assert compare_baskets(unknown(paise), estimated(10**7, fee)) is not (
        Comparison.LEFT_CHEAPER
    )
