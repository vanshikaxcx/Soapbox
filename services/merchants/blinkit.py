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

import json
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Browser, BrowserContext, Page, Route, StorageState

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

# The real, server-derived dark-store id Blinkit assigns for a committed
# location (confirmed live: differs per locality -- e.g. "34748" for
# 110001 vs. "49585" for 400001 -- while the `city` cookie can still read
# the IP-region default underneath, which is exactly what AC-01-04 checks
# for). Cached alongside `_location_state_cache` since both are captured
# together in `_run_location_flow` and both key off pincode.
_zone_id_cache: dict[str, str] = {}

# The human-readable resolved address Blinkit renders in its location bar
# right after a pincode is committed (e.g. "New Delhi, Delhi 110001,
# India") -- confirmed live this element only exists on the homepage
# immediately after commit, not on the search-results/PDP pages evidence
# screenshots are actually taken from, so it has to be captured here and
# carried forward rather than assumed visible in the evidence screenshot.
_address_hint_cache: dict[str, str] = {}

# The precise (float) coordinate Blinkit's own /location/info response
# returns for a committed pincode. Confirmed live (2026-09-20): Blinkit's
# manual pincode-entry flow stores a *truncated integer* lat/lon in its own
# client state (e.g. 28/77 instead of 28.6327426/77.2195969) and sends that
# truncated pair as request headers on every subsequent catalog call --
# its own backend then genuinely rejects the imprecise point as
# "location not serviceable", independent of anything this connector does.
# `_new_context()` below installs a request-header correction using this
# cache so catalog calls carry the precise coordinate Blinkit's own API
# already gave us, rather than the truncated one its client re-derives.
_coordinate_cache: dict[str, tuple[float, float]] = {}

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


def _extract_zone_id(state: StorageState) -> str | None:
    """The `merchant` localStorage key's numeric `id`, as a string.

    Confirmed live (2026-09-19): Blinkit assigns this after a location is
    committed -- it's the dark-store/serviceability-zone Blinkit itself
    resolved from the geocoded pincode, not anything echoed from the
    request. `None` if the key is missing or unparseable (e.g. Blinkit's
    localStorage shape changed) rather than raising -- the caller treats a
    missing zone id the same as any other unavailable-attribute case.
    """
    for origin in state.get("origins", []):
        if "blinkit.com" not in origin.get("origin", ""):
            continue
        for entry in origin.get("localStorage", []):
            if entry.get("name") != "merchant":
                continue
            try:
                merchant_id = json.loads(entry["value"])["id"]
            except (json.JSONDecodeError, KeyError, TypeError):
                return None
            return str(merchant_id)
    return None


def _cached_zone_id(pincode: str) -> str | None:
    with _location_state_lock:
        return _zone_id_cache.get(pincode)


def _cached_address_hint(pincode: str) -> str | None:
    with _location_state_lock:
        return _address_hint_cache.get(pincode)


def _cached_coordinate(pincode: str) -> tuple[float, float] | None:
    with _location_state_lock:
        return _coordinate_cache.get(pincode)


def _extract_address_hint(page: Page) -> str | None:
    """The resolved address text Blinkit's location bar renders after
    commit (e.g. "New Delhi, Delhi 110001, India") -- confirmed live this
    element exists only on the homepage right after location commit, not
    on the search-results/PDP pages evidence screenshots are taken from.
    `None` if the element is missing/empty (layout changed, or called on a
    page that never had it) rather than raising.
    """
    element = page.query_selector('div[class*="LocationBar__Subtitle"]')
    if element is None:
        return None
    text = element.inner_text().strip()
    return text or None


def _lock_for(pincode: str) -> threading.Lock:
    with _pincode_locks_lock:
        lock = _pincode_locks.get(pincode)
        if lock is None:
            lock = threading.Lock()
            _pincode_locks[pincode] = lock
        return lock


def _elapsed_deadline_error(merchant_name: str, deadline: datetime) -> MerchantError | None:
    """`None` if there's still time; a typed TIMEOUT error if there isn't.

    `warm_location()`'s ~8-9s cold flow has no awareness of a caller's
    deadline (see its own docstring: safe to call standalone). Without this
    check, `search()`/`refresh()` called with an already-elapsed deadline
    would still pay that full cost before `_with_page()`'s own (otherwise
    correct) deadline check ever got a chance to run -- confirmed live: an
    elapsed-deadline `search()` call took ~9s instead of returning
    immediately. Checked here, before `warm_location()`, for the same
    reason `_with_page()` checks it before touching the browser pool at all.
    """
    if datetime.now(UTC) >= deadline:
        return MerchantError(
            merchant=merchant_name,
            code=MerchantErrorCode.TIMEOUT,
            message="deadline already elapsed before task started",
            occurred_at=datetime.now(UTC),
        )
    return None


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
        merchant._with_page(
            deadline, lambda page: merchant._run_location_flow(page, location), location
        )


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

    def _new_context(self, browser: Browser, location: Location | None) -> BrowserContext:
        context = super()._new_context(browser, location)
        if location is not None:
            context.route("**/blinkit.com/**", self._correct_location_headers(location.pincode))
        return context

    @staticmethod
    def _correct_location_headers(pincode: str) -> Callable[[Route], None]:
        """Rewrite `lat`/`lon` request headers to the precise coordinate
        `_coordinate_cache` holds for `pincode`, if any -- see that cache's
        module-level docstring for why this is needed. Reads the cache live
        on every request rather than capturing a value at route-install
        time, since a context created during warm_location() has this
        route installed before /location/info's response (and therefore the
        cache entry) exists yet."""

        def handler(route: Route) -> None:
            headers = route.request.headers
            if "lat" not in headers or "lon" not in headers:
                route.continue_()
                return
            coordinate = _cached_coordinate(pincode)
            if coordinate is None:
                route.continue_()
                return
            lat, lon = coordinate
            route.continue_(headers={**headers, "lat": str(lat), "lon": str(lon)})

        return handler

    def _run_location_flow(self, page: Page, location: Location) -> None:
        """The actual UI flow. Only ever invoked via warm_location()'s lock,
        so it never runs twice concurrently for the same pincode."""
        coordinate: dict[str, float] = {}

        def _capture_coordinate(response: Any) -> None:
            if "/location/info" not in response.url:
                return
            try:
                body = response.json()
                coordinate["lat"] = body["coordinate"]["lat"]
                coordinate["lon"] = body["coordinate"]["lon"]
            except Exception:  # noqa: BLE001 - response shape unexpected; leave uncorrected
                return

        page.on("response", _capture_coordinate)

        self._goto(page, "https://blinkit.com/", wait_until="load")
        # Confirmed live (2026-09-20): these selectors render via
        # client-side hydration *after* the `load` event this connector
        # waits for above, not on it -- 5s was reliably enough time on a
        # fast local connection but timed out waiting for "Select manually"
        # from a Fargate task in ap-south-1 (slower CPU/network path, same
        # class of race as the location-commit timing fixed elsewhere in
        # this flow). Bounded generously rather than tuned to one
        # environment's observed speed.
        try:
            page.click('[data-qa-id="close-button"]', timeout=8_000)
        except Exception:  # noqa: BLE001 - app-install banner isn't always shown
            pass
        try:
            page.click('img[alt="Close Slider"]', timeout=10_000)
        except Exception:  # noqa: BLE001 - download-app slider isn't always shown
            pass
        page.click('div[class*="SelectManually"]', timeout=15_000)
        page.fill('input[name="select-locality"]', location.pincode)
        page.wait_for_selector(
            'div[class*="LocationSearchList__LocationListContainer"]', timeout=15_000
        )
        page.click('div[class*="LocationSearchList__LocationListContainer"]')
        # Location commit is an async client-side action with no element to
        # await. A fixed sleep here previously raced two independent signals
        # under higher-latency network paths (confirmed live 2026-09-20:
        # reliable on a low-latency connection, silently wrong from a
        # Fargate task in ap-south-1 -- both the /location/info network
        # response below and, separately, the location bar's own DOM text
        # re-render lagging behind it) -- poll for both real observable
        # conditions instead of guessing a fixed duration for either.
        deadline_ms = 8_000
        waited_ms = 0
        step_ms = 250
        address_bar_ready = (
            "() => { const el = document.querySelector('div[class*=\"LocationBar__Subtitle\"]');"
            " const text = el && el.innerText && el.innerText.trim();"
            " return !!text && text !== 'Select Location'; }"
        )
        while waited_ms < deadline_ms and (
            "lat" not in coordinate or not page.evaluate(address_bar_ready)
        ):
            page.wait_for_timeout(step_ms)
            waited_ms += step_ms

        # Confirmed live (2026-09-20): Blinkit's own /location/info response
        # carries the precise coordinate for the committed pincode, but its
        # client then stores a truncated integer version and sends *that* on
        # every catalog request -- caching the precise value here (before it
        # is needed below) is what lets _correct_location_headers() rewrite
        # those requests back to a serviceable coordinate.
        if "lat" in coordinate:
            with _location_state_lock:
                _coordinate_cache[location.pincode] = (coordinate["lat"], coordinate["lon"])

        # address_hint's element only exists on the homepage right after
        # commit (see _extract_address_hint's docstring) -- capture it before
        # navigating away below, now that the poll above confirmed it's
        # actually rendered rather than still showing the pre-commit
        # placeholder.
        address_hint = _extract_address_hint(page)
        if address_hint is not None:
            with _location_state_lock:
                _address_hint_cache[location.pincode] = address_hint

        # Confirmed live (2026-09-20): the `merchant` (dark-store) id isn't
        # assigned by the location-commit click itself -- it's a side effect
        # of the *next* catalog request. This warm-up visits one (a
        # single-character throwaway query, not a real search) so the
        # session has a merchant id cached before any real search() call.
        # Needs the coordinate correction above already active, since this
        # request would otherwise hit the same truncated-coordinate rejection.
        self._goto(page, "https://blinkit.com/s/?q=a", wait_until="load")
        try:
            page.wait_for_function(
                "() => { try { return !!JSON.parse(localStorage.getItem('merchant') || '{}').id; }"
                " catch (e) { return false; } }",
                timeout=8_000,
            )
        except Exception:  # noqa: BLE001 - proceed with whatever landed; extraction handles None
            pass

        state = page.context.storage_state()
        _cache_state(location.pincode, state)
        zone_id = _extract_zone_id(state)
        if zone_id is not None:
            with _location_state_lock:
                _zone_id_cache[location.pincode] = zone_id

    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[Observation] | MerchantError:
        early_timeout = _elapsed_deadline_error(self.name, deadline)
        if early_timeout is not None:
            return early_timeout
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
        verified_location = location.model_copy(
            update={
                "merchant_zone_id": _cached_zone_id(location.pincode),
                "address_hint": _cached_address_hint(location.pincode),
            }
        )
        # Honest per-request signal, not a blanket "Blinkit is fixed" flag:
        # if this specific pincode's zone id never landed (a future
        # regression, a genuinely unserviceable point), this still reports
        # unverified rather than assuming the fix always holds.
        location_completeness = "verified" if verified_location.merchant_zone_id else "unverified"
        search_url = f"https://blinkit.com/s/?q={quote(item.name)}"
        # Direct navigation, no UI search interaction: confirmed live that
        # this resolves correctly once the context has a location cookie,
        # whether from _run_location_flow() just above or from cache.
        self._goto(page, search_url, wait_until="load")

        try:
            # Bounded generously (see _run_location_flow's comment on the
            # same rendering-speed variance) so a slow render on a
            # higher-latency network path isn't misclassified as
            # genuinely-zero-results below.
            page.wait_for_selector('div[role="button"][id] .tw-text-300', timeout=15_000)
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
                        verified_location=verified_location,
                        location_completeness=location_completeness,
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
        early_timeout = _elapsed_deadline_error(self.name, deadline)
        if early_timeout is not None:
            return early_timeout
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
            verified_location = location.model_copy(
                update={"merchant_zone_id": _cached_zone_id(location.pincode)}
            )
            location_completeness = (
                "verified" if verified_location.merchant_zone_id else "unverified"
            )
            return Observation(
                merchant=self.name,
                sku=sku,
                url=url,
                product_name=name,
                pack_size=pack_size,
                unit=unit,
                price_paise=int(round(float(price) * 100)),
                in_stock=int(unavailable_qty) == 0 and int(inventory) > 0,
                verified_location=verified_location,
                location_completeness=location_completeness,
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
