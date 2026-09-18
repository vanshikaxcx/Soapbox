"""Fallback fee estimates from each merchant's publicly documented policy.

`assess_fees` cannot read a real, current fee without adding items to a live
cart (see blinkit.py / zepto.py module docstrings for why that's
deliberately not attempted). This module fills that gap with a published,
citable fee schedule applied to the already-known basket subtotal, so the
system gets a usable, honestly-labeled number instead of `None`.

Source (checked 2026-09-17): storyboard18.com quick-commerce fee coverage,
dated 2026-06-04. Range values (e.g. "up to Rs 30", "Rs 5-28") resolve to
their upper bound, never the lower one — an estimate must never make a
basket look cheaper than it could turn out to be (see FeeAssessment's
`completeness` field and the spec's ranking-honesty rule). These numbers
are known to drift (Zepto's platform fee was introduced in 2024 and rolled
back by 2025 per the same source) — re-verify against the cited source
periodically; there is no live signal that tells this code when it's stale.
"""

from __future__ import annotations

import hashlib

from .models import Line

# (free_delivery_above_paise, delivery_fee_paise, platform_fee_paise, other_fees_paise)
_BLINKIT_FREE_DELIVERY_ABOVE_PAISE = 199_00
_BLINKIT_DELIVERY_FEE_PAISE = 30_00
_BLINKIT_HANDLING_FEE_PAISE = 11_00  # upper bound of the published Rs 4-11 range

_ZEPTO_FREE_DELIVERY_ABOVE_PAISE = 99_00
_ZEPTO_DELIVERY_FEE_PAISE = 28_00  # upper bound of the published Rs 5-28 range
_ZEPTO_PLATFORM_FEE_PAISE = 2_00
# Zepto's ~Rs 15 late-night surcharge is time-of-day dependent and
# intentionally not modeled — no reliable "is it late night" signal is
# available without a real order timestamp from the checkout flow.


def blinkit_estimated_fees(subtotal_paise: int) -> tuple[int | None, int | None, int | None]:
    """Returns (delivery_fee_paise, platform_fee_paise, other_fees_paise)."""
    free = subtotal_paise >= _BLINKIT_FREE_DELIVERY_ABOVE_PAISE
    delivery_fee = 0 if free else _BLINKIT_DELIVERY_FEE_PAISE
    return delivery_fee, None, _BLINKIT_HANDLING_FEE_PAISE


def zepto_estimated_fees(subtotal_paise: int) -> tuple[int | None, int | None, int | None]:
    """Returns (delivery_fee_paise, platform_fee_paise, other_fees_paise)."""
    free = subtotal_paise >= _ZEPTO_FREE_DELIVERY_ABOVE_PAISE
    delivery_fee = 0 if free else _ZEPTO_DELIVERY_FEE_PAISE
    return delivery_fee, _ZEPTO_PLATFORM_FEE_PAISE, None


def placeholder_line_hash(exact_lines: list[Line]) -> str:
    """Deterministic hash of the basket lines.

    Not the canonical hash WP-02 owns (domain-separated, binds owner/version/
    seller/etc. — see PROOFPATH-SPEC.md sec. on hashing). This is a narrower,
    local stand-in good enough to detect "these are the same lines" until
    WP-02's real hash builder is merged into this tree.
    """
    parts = sorted(f"{line.sku}:{line.quantity}:{line.price_paise}" for line in exact_lines)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
