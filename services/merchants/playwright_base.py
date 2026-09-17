"""Shared Playwright scaffolding for live merchant connectors.

Selectors in blinkit.py are placeholders until the feasibility spike
(scripts/spike_merchant.py) confirms real markup against the tested
locality. zepto.py's selectors are verified (see docs/specs/WP-04).

Each connector picks a `browser_engine` ("chromium" or "lightpanda").
Blinkit stays on Chromium: its Cloudflare bot-management check requires a
real browser TLS fingerprint, which Lightpanda deliberately does not
impersonate. Zepto isn't behind that check, so it runs on Lightpanda for
the latency win (no rendering/CSS/image/font cost). Both engines are
long-lived per container (see browser_pool.py); only the BrowserContext is
per-task.
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import UTC, datetime
from typing import Callable

from playwright.sync_api import BrowserContext, Page

from . import browser_pool
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
    browser_engine: str = "chromium"  # "chromium" | "lightpanda" — set per connector

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

    def _context_options(self, location: Location | None) -> dict:
        """Base new_context() kwargs. Connectors override to add e.g. cached storage_state."""
        options: dict = {
            "viewport": {"width": 390, "height": 844},
            "timezone_id": "Asia/Kolkata",
        }
        if self.browser_engine != "lightpanda":
            # Confirmed live: Playwright's locale="en-IN" trips Zepto's
            # CloudFront WAF when the request comes from Lightpanda (0
            # results / 403, vs. 191 results with locale omitted). Chromium
            # traffic wasn't observed to have this problem.
            options["locale"] = "en-IN"
        if self.browser_engine == "chromium":
            # Confirmed live: bundled headless Chromium's default UA literally
            # contains "HeadlessChrome" (see navigator.userAgent), and
            # Blinkit's Cloudflare rule blocks on that string alone (403 on
            # every request). A normal mobile Chrome UA alone fixes it — no
            # headed browser, stealth args, or navigator.webdriver override
            # were needed once this was isolated.
            options["user_agent"] = (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
            )
        return options

    def _new_context(self, browser, location: Location | None) -> BrowserContext:
        return browser.new_context(**self._context_options(location))

    def _capture_evidence(self, context: BrowserContext, page) -> str:
        try:
            screenshot = page.screenshot(type="png")
            return self.evidence_sink.save(self.name, screenshot, "image/png")
        except Exception:  # noqa: BLE001 - Lightpanda's CDP screenshot support is unverified
            html = page.content().encode("utf-8")
            return self.evidence_sink.save(self.name, html, "text/html")

    def _with_page(
        self, deadline: datetime, task: Callable[[Page], object], location: Location | None = None
    ) -> object | MerchantError:
        """Run `task` against a fresh, isolated page and convert failures to a typed error.

        Shared by search() below and by connectors' own refresh()/assess_fees()
        implementations, which need the same browser/context lifecycle but
        aren't part of the Merchant port's templated call shape. `location` is
        threaded through to _context_options() so a connector can seed the new
        context with cached session state (see blinkit.py) before `task` runs.

        The whole body runs via browser_pool.run_on_engine_thread(): Playwright's
        sync API is confined to whichever thread started its driver, and FastAPI
        can call this method from any thread in its request threadpool —
        confirmed live (two threads calling search() concurrently raised
        `greenlet.error: Cannot switch to a different thread`). See
        browser_pool.py's module docstring for the full explanation.
        """
        remaining_ms = int((deadline - datetime.now(UTC)).total_seconds() * 1000)
        if remaining_ms <= 0:
            return MerchantError(
                merchant=self.name,
                code=MerchantErrorCode.TIMEOUT,
                message="deadline already elapsed before task started",
                occurred_at=datetime.now(UTC),
            )

        def run() -> object | MerchantError:
            browser = browser_pool.get_browser(self.browser_engine)
            context = self._new_context(browser, location)
            try:
                page = context.new_page()
                page.set_default_timeout(min(remaining_ms, self.fetch_deadline_seconds * 1000))
                return task(page)
            except Exception as exc:  # noqa: BLE001 - convert to typed error at the port boundary
                return MerchantError(
                    merchant=self.name,
                    code=self._classify_error(exc),
                    message=str(exc)[:300],
                    occurred_at=datetime.now(UTC),
                )
            finally:
                context.close()  # the shared Browser itself stays alive across tasks

        return browser_pool.run_on_engine_thread(self.browser_engine, run)

    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[Observation] | MerchantError:
        return self._with_page(
            deadline, lambda page: self._search_impl(page, location, item), location
        )

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
