"""Connector contract suite: identical assertions across every registered merchant.

WP-04's spec calls this out as still owed: "a connector contract suite that
runs identically against Blinkit, Zepto, and the fixture connector (same
assertions, parametrized by merchant)." None of these assertions need a real
browser or network call:

- `assess_fees()` on every connector is a pure function of the given lines
  (confirmed by reading blinkit.py/zepto.py/fixture.py: no `_with_page`, no
  Playwright import in the call path) -- safe and fast to call directly.
- An already-elapsed `search()` deadline is checked in `_with_page`
  (`playwright_base.py`) *before* `browser_pool.get_browser()` is ever
  called, so it never launches a browser either.

Anything that needs a live page actually fetching a real product belongs in
`tests/live`, not here.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from services.merchants.base import Merchant
from services.merchants.blinkit import BlinkitMerchant
from services.merchants.fixture import FixtureMerchant
from services.merchants.models import ItemQuery, Line, Location, Mode
from services.merchants.registry import LIVE_MERCHANT_NAMES, build_registry
from services.merchants.zepto import ZeptoMerchant

LOCATION = Location(locality="Connaught Place", pincode="110001")
ELAPSED_DEADLINE = datetime.now(UTC) - timedelta(seconds=1)
FUTURE_DEADLINE = datetime.now(UTC) + timedelta(seconds=45)
EXACT_LINES = [Line(sku="rice", quantity=1, price_paise=50_000)]

#: Generous but real: proves these calls short-circuit rather than merely
#: "eventually" return -- a regression that silently started launching a
#: browser here would take seconds, not milliseconds.
MAX_WALL_SECONDS = 2.0


class FakeEvidenceSink:
    """In-memory `EvidenceSink` -- contract tests never touch disk or S3."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, bytes, str]] = []

    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        self.saved.append((merchant, content, content_type))
        return f"{merchant}/fake-{len(self.saved)}"


LIVE_CONNECTORS: list[tuple[str, Merchant]] = [
    ("blinkit", BlinkitMerchant(FakeEvidenceSink())),
    ("zepto", ZeptoMerchant(FakeEvidenceSink())),
]
FIXTURE_CONNECTORS: list[tuple[str, Merchant]] = [
    ("blinkit", FixtureMerchant("blinkit")),
    ("zepto", FixtureMerchant("zepto")),
]
ALL_CONNECTORS: list[tuple[str, Merchant]] = LIVE_CONNECTORS + FIXTURE_CONNECTORS
ALL_IDS = ["blinkit-live", "zepto-live", "blinkit-fixture", "zepto-fixture"]


def _params(connectors: list[tuple[str, Merchant]], ids: list[str]) -> dict[str, object]:
    return {"argnames": "name,merchant", "argvalues": connectors, "ids": ids}


# -- every connector: port compliance ------------------------------------------


@pytest.mark.parametrize(**_params(ALL_CONNECTORS, ALL_IDS))
def test_every_connector_implements_the_merchant_port(name: str, merchant: Merchant) -> None:
    assert isinstance(merchant, Merchant)


@pytest.mark.parametrize(**_params(ALL_CONNECTORS, ALL_IDS))
def test_every_connector_reports_its_own_registry_name(name: str, merchant: Merchant) -> None:
    assert merchant.name == name


# -- every connector: assess_fees is pure, honest, and never negative ---------


@pytest.mark.parametrize(**_params(ALL_CONNECTORS, ALL_IDS))
def test_assess_fees_is_fast_and_never_raises(name: str, merchant: Merchant) -> None:
    started = time.monotonic()
    result = merchant.assess_fees(LOCATION, EXACT_LINES, FUTURE_DEADLINE)
    elapsed = time.monotonic() - started
    assert elapsed < MAX_WALL_SECONDS, (
        f"{name}.assess_fees() took {elapsed:.2f}s; a pure fee estimate should "
        "never touch a browser or the network"
    )
    assert result is None or result.completeness in {"complete", "estimated", "unknown"}


@pytest.mark.parametrize(**_params(ALL_CONNECTORS, ALL_IDS))
def test_assess_fees_never_returns_a_negative_charge(name: str, merchant: Merchant) -> None:
    result = merchant.assess_fees(LOCATION, EXACT_LINES, FUTURE_DEADLINE)
    assert result is not None
    for value in (result.delivery_fee_paise, result.platform_fee_paise, result.other_fees_paise):
        assert value is None or value >= 0


@pytest.mark.parametrize(**_params(LIVE_CONNECTORS, ["blinkit", "zepto"]))
def test_live_connectors_never_claim_a_complete_fee(name: str, merchant: Merchant) -> None:
    """Regression guard for the honesty rule itself: a live connector that
    started returning "complete" would be claiming a real-time fee neither
    actually reads (see WP-04 spec, "Fee estimation")."""
    result = merchant.assess_fees(LOCATION, EXACT_LINES, FUTURE_DEADLINE)
    assert result is not None
    assert result.completeness == "estimated"


def test_fixture_connector_reports_a_complete_fee() -> None:
    """WP-06 depends on exactly this distinction to demonstrate a provable
    comparison winner in fixture mode (two "estimated" baskets can never be
    ranked against each other under WP-02's honesty rule)."""
    fixture = FixtureMerchant("blinkit")
    result = fixture.assess_fees(LOCATION, EXACT_LINES, FUTURE_DEADLINE)
    assert result is not None
    assert result.completeness == "complete"


# -- live connectors: deadline and allowlist enforcement -----------------------


@pytest.mark.parametrize(**_params(LIVE_CONNECTORS, ["blinkit", "zepto"]))
def test_search_with_an_elapsed_deadline_never_touches_the_browser(
    name: str, merchant: Merchant
) -> None:
    started = time.monotonic()
    result = merchant.search(
        LOCATION, ItemQuery(name="rice", quantity=5.0, unit="kg"), ELAPSED_DEADLINE
    )
    elapsed = time.monotonic() - started
    assert elapsed < MAX_WALL_SECONDS, (
        f"{name}.search() with an already-elapsed deadline took {elapsed:.2f}s; "
        "it should short-circuit before browser_pool.get_browser() is called"
    )
    assert result.code.value == "timeout"  # type: ignore[union-attr]


@pytest.mark.parametrize(**_params(LIVE_CONNECTORS, ["blinkit", "zepto"]))
def test_allowlist_blocks_navigation_outside_the_merchants_own_domain(
    name: str, merchant: Merchant
) -> None:
    with pytest.raises(ValueError):
        merchant._assert_allowed("https://evil.example/steal")  # type: ignore[attr-defined]


@pytest.mark.parametrize(**_params(LIVE_CONNECTORS, ["blinkit", "zepto"]))
def test_allowlist_permits_the_merchants_own_domain(name: str, merchant: Merchant) -> None:
    own_domain = next(iter(merchant._allowed_domains()))  # type: ignore[attr-defined]
    merchant._assert_allowed(f"https://{own_domain}/some/path")  # type: ignore[attr-defined]


# -- fixture connectors: safe to actually call search() ------------------------


@pytest.mark.parametrize(**_params(FIXTURE_CONNECTORS, ["blinkit-fixture", "zepto-fixture"]))
def test_fixture_search_never_returns_another_merchants_observation(
    name: str, merchant: Merchant
) -> None:
    observations = merchant.search(
        LOCATION, ItemQuery(name="rice", quantity=5.0, unit="kg"), FUTURE_DEADLINE
    )
    assert isinstance(observations, list)
    assert observations, f"fixture catalog for {name!r} returned nothing for 'rice'"
    for observation in observations:
        assert observation.merchant == name
        assert observation.mode is Mode.FIXTURE


# -- registry: live and fixture are never mixed --------------------------------


def test_live_registry_covers_exactly_the_declared_live_merchant_names() -> None:
    registry = build_registry(Mode.LIVE)
    assert set(registry) == set(LIVE_MERCHANT_NAMES)
    for merchant_id, merchant in registry.items():
        assert merchant.name == merchant_id
        assert not isinstance(merchant, FixtureMerchant)


def test_fixture_registry_covers_exactly_the_declared_live_merchant_names() -> None:
    """Same name set as the live registry -- the fixture registry stands in
    for a live one, so callers must never notice a naming difference."""
    registry = build_registry(Mode.FIXTURE)
    assert set(registry) == set(LIVE_MERCHANT_NAMES)
    for merchant in registry.values():
        assert isinstance(merchant, FixtureMerchant)
