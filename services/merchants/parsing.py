"""Text-extraction helpers shared by connectors."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import ElementHandle


def require_text(element: ElementHandle | None) -> str:
    """Read `.inner_text()` off a query_selector() result, or fail loudly.

    query_selector() returns None when the selector doesn't match; calling
    .inner_text() on None is a crash, not a typed failure. Both connectors
    wrap card extraction in a try/except that skips the card on any
    exception — raising ValueError here is what actually triggers that
    skip, rather than letting an untyped AttributeError do it implicitly.
    """
    if element is None:
        raise ValueError("expected element not found")
    return element.inner_text()


def parse_inr_to_paise(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    return int(round(float(digits) * 100)) if digits else 0


def parse_pack_size(text: str) -> tuple[float, str] | None:
    """Parse "1 pack (1 kg)" / "500 g" / "5 kg" style pack-size text.

    Mass/volume units take priority over an outer "N pack" count: "1 pack
    (1 kg)" must resolve to 1 kg, not 1 pack.
    """
    lowered = text.lower()
    for unit_group in (r"kg|g|l|ml", r"pack|pcs"):
        match = re.search(rf"([\d.]+)\s*({unit_group})\b", lowered)
        if match:
            return float(match.group(1)), match.group(2)
    return None
