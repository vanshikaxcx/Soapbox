"""Blinkit connector. Selectors are placeholders — confirm with scripts/spike_merchant.py
against the tested locality before trusting extraction results."""
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

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
from .playwright_base import PlaywrightMerchant


class BlinkitMerchant(PlaywrightMerchant):
    name = "blinkit"

    def _search_impl(self, page, location: Location, item: ItemQuery):
        page.goto("https://blinkit.com/", wait_until="domcontentloaded")

        # TODO(spike): confirm real location-picker flow and selector names.
        page.fill('[data-testid="location-search-box"]', location.pincode)
        page.click(f'text="{location.pincode}"')

        search_url = f"https://blinkit.com/s/?q={quote(item.name)}"
        self._assert_allowed(search_url)
        page.goto(search_url, wait_until="domcontentloaded")

        cards = page.query_selector_all('[data-testid="plp-product"]')
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
                name = card.query_selector('[data-testid="product-name"]').inner_text()
                price_text = card.query_selector('[data-testid="product-price"]').inner_text()
                price_paise = _parse_inr_to_paise(price_text)
                sku_url = card.query_selector("a").get_attribute("href") or ""
                observations.append(
                    Observation(
                        merchant=self.name,
                        sku=sku_url.rsplit("/", 1)[-1] or name,
                        url=f"https://blinkit.com{sku_url}",
                        product_name=name,
                        pack_size=item.quantity,
                        unit=item.unit,
                        price_paise=price_paise,
                        in_stock=True,
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

    def refresh(self, location: Location, sku: str, deadline: datetime):
        raise NotImplementedError("wire after search selectors are confirmed by the spike")

    def assess_fees(
        self, location: Location, exact_lines: list[Line], deadline: datetime
    ) -> FeeAssessment | None:
        return None  # unknown until checkout-page fee scraping is implemented


def _parse_inr_to_paise(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    return int(round(float(digits) * 100)) if digits else 0
