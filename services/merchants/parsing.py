"""Text-extraction helpers shared by connectors."""
from __future__ import annotations

import re


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
