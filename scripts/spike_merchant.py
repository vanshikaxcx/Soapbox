"""Manual feasibility spike — run this BEFORE trusting blinkit.py / zepto.py.

Opens a real (non-headless) browser, navigates to the merchant, tries to set
the test locality, searches one item, and dumps the page HTML plus a
screenshot so you can find real selectors. This is throwaway; it is not part
of the agent container.

Usage:
    python scripts/spike_merchant.py blinkit "rice 5kg" 110001
    python scripts/spike_merchant.py zepto "rice 5kg" 110001
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MERCHANT_URLS = {
    "blinkit": "https://blinkit.com/",
    "zepto": "https://www.zeptonow.com/",
}


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(1)

    merchant, query, pincode = sys.argv[1], sys.argv[2], sys.argv[3]
    if merchant not in MERCHANT_URLS:
        raise SystemExit(f"unknown merchant '{merchant}', expected one of {list(MERCHANT_URLS)}")

    out_dir = Path(".spike") / merchant
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context(viewport={"width": 390, "height": 844}, locale="en-IN")
        page = context.new_page()

        print(f"Navigating to {MERCHANT_URLS[merchant]} ...")
        page.goto(MERCHANT_URLS[merchant], wait_until="domcontentloaded")
        page.screenshot(path=str(out_dir / "01_landing.png"))
        (out_dir / "01_landing.html").write_text(page.content())

        print(f"Pausing for manual inspection / interaction.")
        print(f"Try setting pincode {pincode} and searching for '{query}' by hand in the")
        print("opened browser window, then press Enter here to capture the result state.")
        input("Press Enter once the search results are visible...")

        page.screenshot(path=str(out_dir / "02_search_result.png"))
        (out_dir / "02_search_result.html").write_text(page.content())
        print(f"Saved landing + result screenshots/HTML under {out_dir}/")
        print("Use the HTML to find real data-testid/class selectors for the connector.")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
