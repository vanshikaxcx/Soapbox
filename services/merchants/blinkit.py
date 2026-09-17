"""Blinkit connector. Stays on real Chromium (browser_engine, set below):
Blinkit sits behind Cloudflare bot management. Two things were confirmed
live and matter here:

1. TLS/UA fingerprint: Lightpanda gets an immediate 403 from Blinkit's
   Cloudflare edge (it deliberately won't impersonate a real browser).
   Bundled headless Chromium *also* got a 403 initially — its default UA
   literally contains the string "HeadlessChrome", which Cloudflare blocks
   on directly. A normal Chrome UA (set in playwright_base._new_context)
   was the actual, sufficient fix; no headed browser or stealth args were
   needed once this was isolated.

2. Location is a hard gate, unlike Zepto's silent IP-based default: no
   catalog or search renders until a location is explicitly selected. The
   real flow (captured live 2026-09-15): close the app-install banner
   (data-qa-id="close-button", not always shown) -> close the
   download-app/location slider (img[alt="Close Slider"], not always
   shown) -> click "Select manually" -> type the pincode into
   input[name="select-locality"] -> click the first suggestion.

   Confirmed live: that flow's outcome is cookie/localStorage state
   (`context.storage_state()`), not anything server-side tied to this one
   page. A fresh context seeded with that saved state on creation shows the
   location already applied — no modal, no flow — and can then navigate
   *directly* to a search or PDP URL (blinkit.com/prn/x/prid/<id> resolves
   correctly with a placeholder slug once location is set). This cuts a
   ~9s call to ~2-3s after the first request for a given pincode. The
   per-task BrowserContext is still fresh and isolated each time — only the
   cookie jar is reused, exactly like a browser reopening a saved session.

Search results have no stable data-testid; the extraction below is scoped
to div[role="button"] elements with a numeric id (that id is the same
"prid" used in PDP URLs) using the Tailwind utility classes observed live.
This is more fragile than Zepto's data-slot-id attributes and is exactly
the kind of thing scripts/spike_merchant.py exists to re-verify.
"""
from __future__ import annotations

import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Page, StorageState

from .evidence import LocalDiskEvidenceSink
from .fees import blinkit_estimated_fees, placeholder_line_hash
from .models import (
    ExtractionStatus,
    FeeAssessment,
    ItemQuery,
    Line,
    Location,
    MerchantError,
    MerchantErrorCode,
    Mode,
    Observation,
)
from .parsing import parse_inr_to_paise, parse_pack_size, require_text
from .playwright_base import PlaywrightMerchant

# PDP's embedded cart-action payload (see module docstring). Field order
# confirmed live; a Blinkit markup change could reorder or rename these.
_CART_ITEM_RE = re.compile(
    r'"product_id":(\d+),"merchant_id":\d+,"product_name":"([^"]*)",'
    r'"quantity":\d+,"unavailable_quantity":(\d+),"price":([\d.]+),'
    r'"mrp":[\d.]+,"unit":"([^"]*)","inventory":(\d+)'
)

# Session state (cookies/localStorage) per pincode, captured once and reused
# by every subsequent task for that locality. Process-lifetime cache, no
# expiry: a stale entry fails the same way an expired real session would
# (empty results / layout-changed), which is already a handled error path.
_location_state_lock = threading.Lock()
_location_state_cache: dict[str, StorageState] = {}

# One lock per pincode, created lazily, so concurrent callers for the same
# pincode block on each other (run the slow flow once) while callers for a
# *different* pincode aren't held up by it.
_pincode_locks_lock = threading.Lock()
_pincode_locks: dict[str, threading.Lock] = {}


def _cached_state(pincode: str) -> StorageState | None:
    with _location_state_lock:
        return _location_state_cache.get(pincode)


def _cache_state(pincode: str, state: StorageState) -> None:
    with _location_state_lock:
        _location_state_cache[pincode] = state


def _lock_for(pincode: str) -> threading.Lock:
    with _pincode_locks_lock:
        lock = _pincode_locks.get(pincode)
        if lock is None:
            lock = threading.Lock()
            _pincode_locks[pincode] = lock
        return lock


def warm_location(pincode: str, fetch_deadline_seconds: int = 45) -> None:
    """Populate the session-state cache for `pincode`, if not already cached.

    Thread-safe and idempotent: concurrent callers for the same pincode
    block on one flow instead of each running their own ~8s manual
    location-selection. Safe to call standalone — e.g. at container
    startup, before any real request exists — since it only needs a
    throwaway page, not a real search/refresh call.
    """
    if _cached_state(pincode) is not None:
        return
    with _lock_for(pincode):
        if _cached_state(pincode) is not None:
            return  # populated by another caller while we waited for the lock
        # evidence_sink is unused on this path (_run_location_flow never
        # captures evidence); any sink implementation works here.
        merchant = BlinkitMerchant(LocalDiskEvidenceSink())
        location = Location(locality="", pincode=pincode)
        deadline = datetime.now(UTC) + timedelta(seconds=fetch_deadline_seconds)
        merchant._with_page(deadline, lambda page: merchant._run_location_flow(page, location))


class BlinkitMerchant(PlaywrightMerchant):
    name = "blinkit"
    browser_engine = "chromium"

    def _context_options(self, location: Location | None) -> dict[str, Any]:
        options = super()._context_options(location)
        if location is not None:
            cached = _cached_state(location.pincode)
            if cached is not None:
                options["storage_state"] = cached
        return options

    def _run_location_flow(self, page: Page, location: Location) -> None:
        """The actual UI flow. Only ever invoked via warm_location()'s lock,
        so it never runs twice concurrently for the same pincode."""
        self._goto(page, "https://blinkit.com/", wait_until="load")
        try:
            page.click('[data-qa-id="close-button"]', timeout=3_000)
        except Exception:  # noqa: BLE001 - app-install banner isn't always shown
            pass
        try:
            page.click('img[alt="Close Slider"]', timeout=5_000)
        except Exception:  # noqa: BLE001 - download-app slider isn't always shown
            pass
        page.click('div[class*="SelectManually"]', timeout=5_000)
        page.fill('input[name="select-locality"]', location.pincode)
        page.wait_for_selector(
            'div[class*="LocationSearchList__LocationListContainer"]', timeout=5_000
        )
        page.click('div[class*="LocationSearchList__LocationListContainer"]')
        # Location commit is an async client-side action with no element to
        # await; a short settle time was needed live before navigating on.
        page.wait_for_timeout(1_500)
        _cache_state(location.pincode, page.context.storage_state())

    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[Observation] | MerchantError:
        # Block here, before _with_page() creates this task's own context, so
        # that context creation's _context_options() cache lookup below is
        # guaranteed to see a populated cache rather than racing warm-up.
        warm_location(location.pincode)
        return super().search(location, item, deadline)

    def _search_impl(
        self, page: Page, location: Location, item: ItemQuery
    ) -> list[Observation] | MerchantError:
        if _cached_state(location.pincode) is None:
            # Defensive fallback only: search() above already calls
            # warm_location(), so this runs in practice only if this method
            # is invoked some other way.
            self._run_location_flow(page, location)
        search_url = f"https://blinkit.com/s/?q={quote(item.name)}"
        # Direct navigation, no UI search interaction: confirmed live that
        # this resolves correctly once the context has a location cookie,
        # whether from _run_location_flow() just above or from cache.
        self._goto(page, search_url, wait_until="load")

        try:
            page.wait_for_selector('div[role="button"][id] .tw-text-300', timeout=10_000)
        except Exception:  # noqa: BLE001 - genuinely no results, not a stale selector
            return MerchantError(
                merchant=self.name,
                code=MerchantErrorCode.NOT_FOUND,
                message=f"no results for '{item.name}'",
                occurred_at=datetime.now(UTC),
            )

        cards = [
            c
            for c in page.query_selector_all('div[role="button"][id]')
            if (c.get_attribute("id") or "").isdigit()
        ]
        if not cards:
            return MerchantError(
                merchant=self.name,
                code=MerchantErrorCode.NOT_FOUND,
                message=f"no results for '{item.name}'",
                occurred_at=datetime.now(UTC),
            )

        evidence_key = self._capture_evidence(page.context, page)
        observations: list[Observation] = []
        for card in cards[:10]:
            try:
                name = require_text(
                    card.query_selector(".tw-text-300.tw-font-semibold.tw-line-clamp-2")
                )
                price_text = require_text(card.query_selector(".tw-text-200.tw-font-semibold"))
                pack_el = card.query_selector(
                    ".tw-text-200.tw-font-medium.tw-line-clamp-1.tw-text-base-green"
                )
                pack_size, unit = parse_pack_size(pack_el.inner_text() if pack_el else "") or (
                    item.quantity,
                    item.unit,
                )
                sku = card.get_attribute("id") or ""
                observations.append(
                    Observation(
                        merchant=self.name,
                        sku=sku,
                        # Placeholder slug: confirmed live that Blinkit resolves
                        # by prid alone once the session has a location set.
                        url=f"https://blinkit.com/prn/x/prid/{sku}",
                        product_name=name,
                        pack_size=pack_size,
                        unit=unit,
                        price_paise=parse_inr_to_paise(price_text),
                        # Confirmed live (query "rare spice" surfaced one):
                        # an out-of-stock card overlays the literal text
                        # "Out of Stock" on the product image. Checking
                        # inner_text() rather than a specific badge class
                        # keeps this robust to layout/class changes.
                        in_stock="Out of Stock" not in card.inner_text(),
                        verified_location=location,
                        fetch_time=datetime.now(UTC),
                        evidence_key=evidence_key,
                        extraction_status=ExtractionStatus.OK,
                        mode=Mode.LIVE,
                    )
                )
            except Exception:  # noqa: BLE001 - skip malformed cards, don't fail whole search
                continue

        if not observations:
            return MerchantError(
                merchant=self.name,
                code=MerchantErrorCode.LAYOUT_CHANGED,
                message="cards found but none parsed; selectors likely stale",
                occurred_at=datetime.now(UTC),
            )
        return observations

    def refresh(
        self, location: Location, sku: str, deadline: datetime
    ) -> Observation | MerchantError:
        # Same reasoning as search() above: block before this task's own
        # context is created, so its _context_options() cache lookup sees a
        # populated cache instead of racing warm-up.
        warm_location(location.pincode)
        url = f"https://blinkit.com/prn/x/prid/{sku}"
        self._assert_allowed(url)

        def task(page: Page) -> Observation | MerchantError:
            if _cached_state(location.pincode) is None:
                self._run_location_flow(page, location)  # defensive fallback, see _search_impl
            self._goto(page, url, wait_until="load")
            page.wait_for_timeout(1_500)  # PDP hydration; no single element reliably marks "ready"

            # Confirmed live: the same cart-item payload shape repeats for
            # every item in "similar products" / "frequently bought
            # together" carousels on the PDP, in no guaranteed order — the
            # requested sku is sometimes the *last* match, not the first.
            # re.search() alone silently returns whichever item topped the
            # page, which is a real, reproduced bug, not a hypothetical one.
            match = next(
                (m for m in _CART_ITEM_RE.finditer(page.content()) if m.group(1) == sku),
                None,
            )
            if not match:
                return MerchantError(
                    merchant=self.name,
                    code=MerchantErrorCode.LAYOUT_CHANGED,
                    message="cart-item payload missing; PDP markup likely changed",
                    occurred_at=datetime.now(UTC),
                )

            _pid, name, unavailable_qty, price, unit_text, inventory = match.groups()
            pack_size, unit = parse_pack_size(unit_text) or (1.0, "pack")
            return Observation(
                merchant=self.name,
                sku=sku,
                url=url,
                product_name=name,
                pack_size=pack_size,
                unit=unit,
                price_paise=int(round(float(price) * 100)),
                in_stock=int(unavailable_qty) == 0 and int(inventory) > 0,
                verified_location=location,
                fetch_time=datetime.now(UTC),
                evidence_key=self._capture_evidence(page.context, page),
                extraction_status=ExtractionStatus.OK,
                mode=Mode.LIVE,
            )

        return self._with_page(deadline, task, location)

    def assess_fees(
        self, location: Location, exact_lines: list[Line], deadline: datetime
    ) -> FeeAssessment | None:
        # A real, current fee needs a live cart (see module docstring for why
        # that's deliberately not attempted). This falls back to Blinkit's
        # published fee policy applied to the known subtotal — see fees.py
        # for the source and the "never understate cost" rounding rule.
        subtotal_paise = sum(line.price_paise * int(line.quantity) for line in exact_lines)
        delivery_fee, platform_fee, other_fees = blinkit_estimated_fees(subtotal_paise)
        return FeeAssessment(
            merchant=self.name,
            location=location,
            line_hash=placeholder_line_hash(exact_lines),
            subtotal_paise=subtotal_paise,
            delivery_fee_paise=delivery_fee,
            platform_fee_paise=platform_fee,
            other_fees_paise=other_fees,
            completeness="estimated",
            fetch_time=datetime.now(UTC),
        )
