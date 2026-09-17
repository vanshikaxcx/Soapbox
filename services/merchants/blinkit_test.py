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
from services.merchants.blinkit import BlinkitMerchant
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
    result = merchant.search(LOCATION, ItemQuery(name="rice", quantity=5.0, unit="kg"),
                              ELAPSED_DEADLINE)
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
    monkeypatch.setattr(
        PlaywrightMerchant, "search", lambda self, location, item, deadline: []
    )
    merchant = BlinkitMerchant(evidence_sink=_UnusedEvidenceSink())
    future_deadline = datetime.now(UTC) + timedelta(seconds=45)
    merchant.search(LOCATION, ItemQuery(name="rice", quantity=5.0, unit="kg"), future_deadline)
    assert calls == ["110001"]


class _UnusedEvidenceSink:
    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        raise AssertionError("evidence sink should not be touched by these tests")
