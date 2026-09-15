"""Shared Playwright scaffolding for live merchant connectors.

Selectors in blinkit.py / zepto.py are placeholders until the feasibility
spike (scripts/spike_merchant.py) confirms real markup against the tested
locality. Do not trust them without running the spike first.
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import UTC, datetime

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from .base import Merchant
from .evidence import EvidenceSink
from .models import ItemQuery, Location, MerchantError, MerchantErrorCode, Observation

# Domain allowlist enforced before any navigation. Never navigate elsewhere,
# including redirect targets.
ALLOWED_DOMAINS: dict[str, set[str]] = {
    "blinkit": {"blinkit.com", "www.blinkit.com"},
    "zepto": {"zeptonow.com", "www.zeptonow.com"},
}


class PlaywrightMerchant(Merchant):
    def __init__(self, evidence_sink: EvidenceSink, fetch_deadline_seconds: int = 45) -> None:
        self.evidence_sink = evidence_sink
        self.fetch_deadline_seconds = fetch_deadline_seconds

    def _allowed_domains(self) -> set[str]:
        return ALLOWED_DOMAINS[self.name]

    def _assert_allowed(self, url: str) -> None:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        if host not in self._allowed_domains():
            raise ValueError(f"blocked navigation outside allowlist: {host}")

    def _new_context(self, browser: Browser) -> BrowserContext:
        return browser.new_context(
            viewport={"width": 390, "height": 844},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

    def _capture_evidence(self, context: BrowserContext, page) -> str:
        screenshot = page.screenshot(type="png")
        return self.evidence_sink.save(self.name, screenshot, "image/png")

    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[Observation] | MerchantError:
        remaining_ms = int((deadline - datetime.now(UTC)).total_seconds() * 1000)
        if remaining_ms <= 0:
            return MerchantError(
                merchant=self.name,
                code=MerchantErrorCode.TIMEOUT,
                message="deadline already elapsed before fetch started",
                occurred_at=datetime.now(UTC),
            )

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = self._new_context(browser)
            try:
                page = context.new_page()
                page.set_default_timeout(min(remaining_ms, self.fetch_deadline_seconds * 1000))
                return self._search_impl(page, location, item)
            except Exception as exc:  # noqa: BLE001 - convert to typed error at the port boundary
                return MerchantError(
                    merchant=self.name,
                    code=self._classify_error(exc),
                    message=str(exc)[:300],
                    occurred_at=datetime.now(UTC),
                )
            finally:
                context.close()
                browser.close()

    def _classify_error(self, exc: Exception) -> MerchantErrorCode:
        text = str(exc).lower()
        if "timeout" in text:
            return MerchantErrorCode.TIMEOUT
        if "captcha" in text:
            return MerchantErrorCode.CAPTCHA
        return MerchantErrorCode.UNKNOWN

    @abstractmethod
    def _search_impl(
        self, page, location: Location, item: ItemQuery
    ) -> list[Observation] | MerchantError:
        """Merchant-specific navigation/scraping. Implemented by each connector."""
