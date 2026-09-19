"""Blinkit-specific white-box coverage: the deadline-before-warm-up fix.

`search()`/`refresh()` used to call `warm_location()` -- a real ~9s cold
Playwright flow -- before ever checking whether the caller's deadline had
already elapsed. Confirmed live (twice, unintentionally, against production
blinkit.com, before this was understood -- see the WP-06 spec's addendum):
an elapsed-deadline `search()` call took ~9s instead of returning
immediately. These tests monkeypatch `warm_location` to a spy rather than
calling the real one, specifically so this never needs a second live hit to
stay covered -- a cache-warm rerun of the old bug would otherwise look fast
too, without actually proving `warm_location` was skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.merchants import blinkit as blinkit_module
from services.merchants.blinkit import (
    BlinkitMerchant,
    _extract_address_hint,
    _extract_zone_id,
    _verified_location,
)
from services.merchants.models import ItemQuery, Location, MerchantErrorCode
from services.merchants.playwright_base import PlaywrightMerchant

LOCATION = Location(locality="Connaught Place", pincode="110001")
ELAPSED_DEADLINE = datetime.now(UTC) - timedelta(seconds=1)


def _never_call(*args: object, **kwargs: object) -> None:
    raise AssertionError("warm_location() must not be called once the deadline has elapsed")


def test_search_never_calls_warm_location_once_the_deadline_has_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(blinkit_module, "warm_location", _never_call)
    merchant = BlinkitMerchant(evidence_sink=_UnusedEvidenceSink())
    result = merchant.search(
        LOCATION, ItemQuery(name="rice", quantity=5.0, unit="kg"), ELAPSED_DEADLINE
    )
    assert result.code is MerchantErrorCode.TIMEOUT  # type: ignore[union-attr]


def test_refresh_never_calls_warm_location_once_the_deadline_has_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(blinkit_module, "warm_location", _never_call)
    merchant = BlinkitMerchant(evidence_sink=_UnusedEvidenceSink())
    result = merchant.refresh(LOCATION, "some-sku", ELAPSED_DEADLINE)
    assert result.code is MerchantErrorCode.TIMEOUT  # type: ignore[union-attr]


def test_search_still_warms_location_when_time_remains(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fix must only skip warm-up when the deadline has passed -- not always."""
    calls: list[str] = []
    monkeypatch.setattr(blinkit_module, "warm_location", lambda pincode: calls.append(pincode))
    # Patch the base connector's browser-touching half out too: this test is
    # only proving *which pincode/whether* warm_location is called, not
    # exercising a real page fetch.
    monkeypatch.setattr(PlaywrightMerchant, "search", lambda self, location, item, deadline: [])
    merchant = BlinkitMerchant(evidence_sink=_UnusedEvidenceSink())
    future_deadline = datetime.now(UTC) + timedelta(seconds=45)
    merchant.search(LOCATION, ItemQuery(name="rice", quantity=5.0, unit="kg"), future_deadline)
    assert calls == ["110001"]


def _state_with_merchant(value: str, origin: str = "https://blinkit.com") -> dict[str, object]:
    return {
        "cookies": [],
        "origins": [{"origin": origin, "localStorage": [{"name": "merchant", "value": value}]}],
    }


def test_extract_zone_id_reads_the_merchant_localstorage_id() -> None:
    """Confirmed live 2026-09-19: differs per locality (34748 for 110001 vs.
    49585 for 400001) -- this is the real server-derived identifier AC-01-04
    needs, not an echo of the input pincode."""
    state = _state_with_merchant('{"id":34748}')
    assert _extract_zone_id(state) == "34748"  # type: ignore[arg-type]


def test_extract_zone_id_is_none_when_merchant_key_is_absent() -> None:
    state: dict[str, object] = {
        "cookies": [],
        "origins": [{"origin": "https://blinkit.com", "localStorage": []}],
    }
    assert _extract_zone_id(state) is None  # type: ignore[arg-type]


def test_extract_zone_id_is_none_when_value_is_malformed_json() -> None:
    state = _state_with_merchant("not json")
    assert _extract_zone_id(state) is None  # type: ignore[arg-type]


def test_extract_zone_id_is_none_when_id_field_is_missing() -> None:
    state = _state_with_merchant("{}")
    assert _extract_zone_id(state) is None  # type: ignore[arg-type]


def test_extract_zone_id_ignores_other_origins() -> None:
    state = _state_with_merchant('{"id":34748}', origin="https://example.com")
    assert _extract_zone_id(state) is None  # type: ignore[arg-type]


def test_extract_zone_id_ignores_an_origin_that_merely_contains_the_substring() -> None:
    """Regression: a loose `"blinkit.com" in origin` substring match would
    wrongly accept an unrelated origin like this one."""
    state = _state_with_merchant('{"id":34748}', origin="https://blinkit.com.evil.example")
    assert _extract_zone_id(state) is None  # type: ignore[arg-type]


def test_extract_zone_id_accepts_a_blinkit_subdomain() -> None:
    state = _state_with_merchant('{"id":34748}', origin="https://www.blinkit.com")
    assert _extract_zone_id(state) == "34748"  # type: ignore[arg-type]


def test_extract_zone_id_is_none_when_id_field_is_not_a_scalar() -> None:
    """A dict/list under `id` (e.g. after a Blinkit localStorage shape
    change) must not be silently str()-coerced into a garbage zone id."""
    state = _state_with_merchant('{"id":{"nested":1}}')
    assert _extract_zone_id(state) is None  # type: ignore[arg-type]


def test_verified_location_carries_both_cached_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(blinkit_module._zone_id_cache, "110001", "34748")
    monkeypatch.setitem(
        blinkit_module._address_hint_cache, "110001", "New Delhi, Delhi 110001, India"
    )

    result = _verified_location(LOCATION)

    assert result.merchant_zone_id == "34748"
    assert result.address_hint == "New Delhi, Delhi 110001, India"


def test_verified_location_is_none_for_an_uncached_pincode() -> None:
    result = _verified_location(Location(locality="", pincode="000000"))

    assert result.merchant_zone_id is None
    assert result.address_hint is None


class _FakeElement:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class _FakePage:
    """Stands in for a Playwright `Page` for testing `_extract_address_hint`
    without a real browser -- only `query_selector` is exercised."""

    def __init__(self, element: _FakeElement | None) -> None:
        self._element = element

    def query_selector(self, selector: str) -> _FakeElement | None:
        return self._element


def test_extract_address_hint_reads_the_location_bar_text() -> None:
    """Confirmed live 2026-09-19: this element only renders on the homepage
    right after location commit, not on the search-results/PDP pages
    evidence screenshots are taken from -- P4's AC-01-04 ground-truth check
    can't rely on the screenshot alone, so this is captured separately."""
    page = _FakePage(_FakeElement("New Delhi, Delhi 110001, India"))
    assert _extract_address_hint(page) == "New Delhi, Delhi 110001, India"  # type: ignore[arg-type]


def test_extract_address_hint_is_none_when_element_is_missing() -> None:
    page = _FakePage(None)
    assert _extract_address_hint(page) is None  # type: ignore[arg-type]


def test_extract_address_hint_is_none_when_text_is_blank() -> None:
    page = _FakePage(_FakeElement("   "))
    assert _extract_address_hint(page) is None  # type: ignore[arg-type]


class _UnusedEvidenceSink:
    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        raise AssertionError("evidence sink should not be touched by these tests")
