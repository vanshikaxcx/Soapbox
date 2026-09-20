"""Published fee-schedule estimates (WP-04's `fees.py`) had no test coverage.

These are pure functions applied to an already-known subtotal -- no
Playwright, no network -- so they're fast, deterministic, and exactly the
kind of thing that should never have shipped untested. The one rule that
matters most: an estimate must never make a basket look cheaper than it
could turn out to be (SPEC's ranking-honesty rule), which is why every range
value here resolves to its upper bound, not the lower one.
"""

from __future__ import annotations

from services.merchants.fees import (
    _BLINKIT_DELIVERY_FEE_PAISE,
    _BLINKIT_FREE_DELIVERY_ABOVE_PAISE,
    _BLINKIT_HANDLING_FEE_PAISE,
    _ZEPTO_DELIVERY_FEE_PAISE,
    _ZEPTO_FREE_DELIVERY_ABOVE_PAISE,
    _ZEPTO_PLATFORM_FEE_PAISE,
    blinkit_estimated_fees,
    placeholder_line_hash,
    zepto_estimated_fees,
)
from services.merchants.models import Line

# -- blinkit ------------------------------------------------------------------


def test_blinkit_charges_delivery_below_the_free_threshold() -> None:
    delivery, platform, handling = blinkit_estimated_fees(_BLINKIT_FREE_DELIVERY_ABOVE_PAISE - 1)
    assert delivery == _BLINKIT_DELIVERY_FEE_PAISE
    assert handling == _BLINKIT_HANDLING_FEE_PAISE
    assert platform is None  # Blinkit publishes no platform fee


def test_blinkit_delivery_is_free_at_and_above_the_threshold() -> None:
    at_threshold, _, _ = blinkit_estimated_fees(_BLINKIT_FREE_DELIVERY_ABOVE_PAISE)
    above_threshold, _, _ = blinkit_estimated_fees(_BLINKIT_FREE_DELIVERY_ABOVE_PAISE + 100)
    assert at_threshold == 0
    assert above_threshold == 0


def test_blinkit_handling_fee_is_charged_regardless_of_subtotal() -> None:
    """Handling isn't a delivery-threshold rebate; it applies either side."""
    _, _, below = blinkit_estimated_fees(0)
    _, _, above = blinkit_estimated_fees(_BLINKIT_FREE_DELIVERY_ABOVE_PAISE + 100)
    assert below == _BLINKIT_HANDLING_FEE_PAISE
    assert above == _BLINKIT_HANDLING_FEE_PAISE


# -- zepto ----------------------------------------------------------------


def test_zepto_charges_delivery_below_the_free_threshold() -> None:
    delivery, platform, other = zepto_estimated_fees(_ZEPTO_FREE_DELIVERY_ABOVE_PAISE - 1)
    assert delivery == _ZEPTO_DELIVERY_FEE_PAISE
    assert platform == _ZEPTO_PLATFORM_FEE_PAISE
    assert other is None  # Zepto publishes no separate "other" fee


def test_zepto_delivery_is_free_at_and_above_the_threshold() -> None:
    at_threshold, _, _ = zepto_estimated_fees(_ZEPTO_FREE_DELIVERY_ABOVE_PAISE)
    above_threshold, _, _ = zepto_estimated_fees(_ZEPTO_FREE_DELIVERY_ABOVE_PAISE + 100)
    assert at_threshold == 0
    assert above_threshold == 0


def test_zepto_platform_fee_is_charged_regardless_of_delivery_threshold() -> None:
    _, below, _ = zepto_estimated_fees(0)
    _, above, _ = zepto_estimated_fees(_ZEPTO_FREE_DELIVERY_ABOVE_PAISE + 100)
    assert below == _ZEPTO_PLATFORM_FEE_PAISE
    assert above == _ZEPTO_PLATFORM_FEE_PAISE


# -- shared honesty rule: never understate cost --------------------------------


def test_neither_schedule_ever_returns_a_negative_fee() -> None:
    for subtotal in (0, 1, 9_900, 19_900, 1_000_000):
        for delivery, platform, other in (
            blinkit_estimated_fees(subtotal),
            zepto_estimated_fees(subtotal),
        ):
            for value in (delivery, platform, other):
                assert value is None or value >= 0


# -- placeholder_line_hash -----------------------------------------------------


def test_placeholder_line_hash_is_order_independent() -> None:
    """A basket's line order is an artifact of how it was built, not a fact
    about the basket -- the hash must not depend on it."""
    a = Line(sku="rice", quantity=1, price_paise=50_000)
    b = Line(sku="oil", quantity=2, price_paise=15_000)
    assert placeholder_line_hash([a, b]) == placeholder_line_hash([b, a])


def test_placeholder_line_hash_changes_with_the_lines() -> None:
    a = Line(sku="rice", quantity=1, price_paise=50_000)
    b = Line(sku="rice", quantity=1, price_paise=50_001)  # one paisa different
    assert placeholder_line_hash([a]) != placeholder_line_hash([b])
