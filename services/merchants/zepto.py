"""Zepto connector, running on the Lightpanda engine (see playwright_base.py).

Search-card selectors and the PDP's embedded schema.org JSON-LD were
captured and verified against real responses on 2026-09-15, then confirmed
end-to-end through Playwright's connect_over_cdp against a live
`lightpanda serve` instance. Not yet wired: setting an explicit
locality/pincode before search (TODO(spike) — verified runs used Zepto's
IP-inferred default location, not the tested pincode; see
config.TESTED_LOCALITY_PINCODE).

`assess_fees` doesn't read a real, current fee: that needs adding items to
a live cart, which mutates state on Zepto's actual servers — a deliberately
unattempted action here, not a forgotten one. Instead it falls back to
Zepto's published fee policy applied to the known subtotal; see fees.py for
the source and the completeness="estimated" labeling this carries.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import quote

from playwright.sync_api import Page

from .fees import placeholder_line_hash, zepto_estimated_fees
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

_PRODUCT_SCHEMA_RE = re.compile(
    r'<script id="productSchema" type="application/ld\+json">(.*?)</script>', re.S
)


class ZeptoMerchant(PlaywrightMerchant):
    name = "zepto"
    browser_engine = "lightpanda"

    def _search_impl(
        self, page: Page, location: Location, item: ItemQuery
    ) -> list[Observation] | MerchantError:
        # TODO(spike): set location.pincode explicitly before searching; see
        # module docstring. Until then results reflect Zepto's own default
        # serviceability location, not `location`.
        search_url = f"https://www.zeptonow.com/search?query={quote(item.name)}"
        # Waiting for full networkidle costs ~4-5s here because Zepto's page
        # never goes fully idle (background analytics/tracking). Waiting for
        # the actual result cards to appear instead cuts this to ~2s.
        self._goto(page, search_url, wait_until="load")
        try:
            # Confirmed live: waiting on the outer card anchor resolves before
            # its inner spans (name/price) are populated — a real race, not a
            # timing fluke (reproduced 1/1 without this, 0/3 with it). Waiting
            # on a leaf element inside the card avoids it.
            page.wait_for_selector('[data-slot-id="EdlpPrice"] span', timeout=10_000)
        except Exception:  # noqa: BLE001 - genuinely no results, not a stale selector
            return MerchantError(
                merchant=self.name,
                code=MerchantErrorCode.NOT_FOUND,
                message=f"no results for '{item.name}'",
                occurred_at=datetime.now(UTC),
            )

        cards = page.query_selector_all('a[data-testid="product-card"]')
        evidence_key = self._capture_evidence(page.context, page)
        observations: list[Observation] = []
        for card in cards[:10]:
            try:
                name = require_text(card.query_selector('[data-slot-id="ProductName"] span'))
                price_text = require_text(card.query_selector('[data-slot-id="EdlpPrice"] span'))
                price_paise = parse_inr_to_paise(price_text)
                pack_text = require_text(card.query_selector('[data-slot-id="PackSize"] span'))
                pack_size, unit = parse_pack_size(pack_text) or (item.quantity, item.unit)
                out_of_stock = card.query_selector('[data-is-out-of-stock="true"]') is not None
                href = card.get_attribute("href") or ""
                observations.append(
                    Observation(
                        # The full "pn/<slug>/pvid/<id>" path is kept as the
                        # sku (not just the trailing id) because Zepto's PDP
                        # route requires the real slug — a bare pvid 404s.
                        merchant=self.name,
                        sku=href.lstrip("/") or name,
                        url=f"https://www.zeptonow.com{href}",
                        product_name=name,
                        pack_size=pack_size,
                        unit=unit,
                        price_paise=price_paise,
                        in_stock=not out_of_stock,
                        verified_location=location,
                        # Always unverified: this connector doesn't set a
                        # pincode before searching (see module docstring's
                        # TODO(spike)) -- results reflect Zepto's own
                        # IP-inferred default, not the requested locality.
                        location_completeness="unverified",
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
        url = f"https://www.zeptonow.com/{sku.lstrip('/')}"
        self._assert_allowed(url)

        def task(page: Page) -> Observation | MerchantError:
            self._goto(page, url, wait_until="load")
            try:
                # state="attached": a <script> tag is never "visible",
                # Playwright's default wait state.
                page.wait_for_selector("#productSchema", timeout=8_000, state="attached")
            except Exception:  # noqa: BLE001
                return MerchantError(
                    merchant=self.name,
                    code=MerchantErrorCode.NOT_FOUND,
                    message=f"no product schema for sku '{sku}'",
                    occurred_at=datetime.now(UTC),
                )

            match = _PRODUCT_SCHEMA_RE.search(page.content())
            if not match:
                return MerchantError(
                    merchant=self.name,
                    code=MerchantErrorCode.LAYOUT_CHANGED,
                    message="productSchema tag missing; PDP markup likely changed",
                    occurred_at=datetime.now(UTC),
                )

            data = json.loads(match.group(1))
            offer = data.get("offers", {})
            pack_size, unit = parse_pack_size(data.get("description", "")) or (1.0, "pack")
            return Observation(
                merchant=self.name,
                sku=sku,
                url=url,
                product_name=data.get("name", ""),
                pack_size=pack_size,
                unit=unit,
                price_paise=int(round(float(offer.get("price", 0)) * 100)),
                in_stock=offer.get("availability", "").endswith("InStock"),
                verified_location=location,
                location_completeness="unverified",  # see search's comment above
                fetch_time=datetime.now(UTC),
                evidence_key=self._capture_evidence(page.context, page),
                extraction_status=ExtractionStatus.OK,
                mode=Mode.LIVE,
            )

        return self._with_page(deadline, task, location)

    def assess_fees(
        self, location: Location, exact_lines: list[Line], deadline: datetime
    ) -> FeeAssessment | None:
        subtotal_paise = sum(line.price_paise * int(line.quantity) for line in exact_lines)
        delivery_fee, platform_fee, other_fees = zepto_estimated_fees(subtotal_paise)
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
