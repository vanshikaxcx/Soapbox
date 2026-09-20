"""Fake/dev extraction backend (WP-05, P2's slice).

Text: a regex heuristic ("2 kg rice", "500ml milk, 1 dozen eggs") -- good
enough to prove the contract shape and unblock P1's UI, not a substitute for
a real model. Image: a content-hash-keyed fixture table, the same idea as
WP-04's `FixtureMerchant` -- there is no honest non-ML fallback for a photo,
so any image outside the known fixture set comes back `extraction_unavailable`
rather than guessing.

Never invents a hard attribute or a flexibility beyond the domain's own
`exact_only` default: the only hard attribute this heuristic will ever set is
one explicitly named in `_HARD_ATTRIBUTE_KEYWORDS`, taken verbatim from the
shopper's own words.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from .base import Extractor
from .models import CandidateItem, ExtractionResult, UnresolvedCandidate

#: Word -> canonical `services.domain.units.Unit` value.
_UNIT_ALIASES: dict[str, str] = {
    "g": "g",
    "gm": "g",
    "gms": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "kgs": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "ml": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "l": "l",
    "litre": "l",
    "litres": "l",
    "liter": "l",
    "liters": "l",
    "piece": "piece",
    "pieces": "piece",
    "pc": "piece",
    "pcs": "piece",
    "unit": "piece",
    "units": "piece",
    "dozen": "piece",
}

#: A word appearing in the item's own name that names an attribute the
#: shopper stated explicitly -- never inferred, never guessed.
_HARD_ATTRIBUTE_KEYWORDS: dict[str, tuple[str, str]] = {
    "organic": ("type", "organic"),
    "diet": ("type", "diet"),
    "sugar-free": ("type", "sugar_free"),
    "low-fat": ("type", "low_fat"),
    "skimmed": ("type", "skimmed"),
}

_QUANTITY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?\s+(.+?)\s*$")
_SPLIT_RE = re.compile(r",|\band\b|\n", flags=re.IGNORECASE)


def _extract_hard_attributes(name: str) -> dict[str, str]:
    lowered = name.lower()
    for keyword, (attr_name, attr_value) in _HARD_ATTRIBUTE_KEYWORDS.items():
        if keyword in lowered:
            return {attr_name: attr_value}
    return {}


def _parse_fragment(fragment: str) -> CandidateItem | UnresolvedCandidate | None:
    fragment = fragment.strip()
    if not fragment:
        return None

    match = _QUANTITY_RE.match(fragment)
    if not match:
        return UnresolvedCandidate(
            raw_fragment=fragment,
            reason_code="no_quantity_detected",
            reason_detail="no leading quantity found in this fragment",
        )

    quantity_str, unit_word, rest = match.groups()
    quantity_value = float(quantity_str)
    unit = _UNIT_ALIASES.get(unit_word.lower()) if unit_word else None
    name = rest
    if unit is None:
        # The word right after the number wasn't a known unit -- it's part
        # of the item's name (e.g. "2 amul milk"), and a bare count of
        # pieces is a legitimate, explicit reading, not a guess.
        if unit_word:
            name = f"{unit_word} {rest}".strip()
        unit = "piece"

    name = name.strip()
    if not name:
        return UnresolvedCandidate(
            raw_fragment=fragment,
            reason_code="ambiguous_item",
            reason_detail="a quantity was found but no item name followed it",
        )

    return CandidateItem(
        raw_fragment=fragment,
        name=name,
        quantity_value=quantity_value,
        unit=unit,
        hard_attributes=_extract_hard_attributes(name),
        flexibility="exact_only",
    )


class FakeExtractor(Extractor):
    """Deterministic dev/test backend. No network call, no model."""

    name = "fake"

    def extract_from_text(self, transcript: str, deadline: datetime) -> ExtractionResult:
        del deadline  # single-pass regex; nothing to time-box
        fragments = [f for f in _SPLIT_RE.split(transcript) if f.strip()]
        if not fragments:
            return ExtractionResult(
                unresolved=(
                    UnresolvedCandidate(
                        raw_fragment=transcript,
                        reason_code="no_items_detected",
                        reason_detail="nothing resembling a shopping item was found",
                    ),
                )
            )

        candidates: list[CandidateItem] = []
        unresolved: list[UnresolvedCandidate] = []
        for fragment in fragments:
            parsed = _parse_fragment(fragment)
            if parsed is None:
                continue
            if isinstance(parsed, CandidateItem):
                candidates.append(parsed)
            else:
                unresolved.append(parsed)

        if not candidates and not unresolved:
            unresolved.append(
                UnresolvedCandidate(
                    raw_fragment=transcript,
                    reason_code="no_items_detected",
                    reason_detail="nothing resembling a shopping item was found",
                )
            )
        return ExtractionResult(candidates=tuple(candidates), unresolved=tuple(unresolved))

    def extract_from_image(
        self, image_bytes: bytes, mime_type: str, deadline: datetime
    ) -> ExtractionResult:
        del deadline, mime_type
        digest = hashlib.sha256(image_bytes).hexdigest()
        fixture = _IMAGE_FIXTURES.get(digest)
        if fixture is None:
            return ExtractionResult(
                unresolved=(
                    UnresolvedCandidate(
                        raw_fragment=f"<image sha256:{digest[:12]}>",
                        reason_code="extraction_unavailable",
                        reason_detail=(
                            "no fixture matches this image, and no real vision "
                            "backend is configured"
                        ),
                    ),
                )
            )
        return fixture


#: Known-image fixtures, keyed by the sha256 digest of the exact image
#: bytes. No real OCR runs here -- this proves the contract shape only, the
#: same "fixture" idea WP-04 uses for merchant search results.
_FIXTURE_MILK_AND_RICE = b"proofpath-fixture-image:milk-and-rice-list-v1"

_IMAGE_FIXTURES: dict[str, ExtractionResult] = {
    hashlib.sha256(_FIXTURE_MILK_AND_RICE).hexdigest(): ExtractionResult(
        candidates=(
            CandidateItem(
                raw_fragment="<fixture: milk-and-rice-list-v1>",
                name="milk",
                quantity_value=2.0,
                unit="l",
                hard_attributes={},
                flexibility="exact_only",
            ),
            CandidateItem(
                raw_fragment="<fixture: milk-and-rice-list-v1>",
                name="basmati rice",
                quantity_value=5.0,
                unit="kg",
                hard_attributes={},
                flexibility="exact_only",
            ),
        )
    ),
}

#: Exposed for tests: the exact bytes that resolve to the fixture above.
FIXTURE_IMAGE_MILK_AND_RICE = _FIXTURE_MILK_AND_RICE

__all__ = ["FIXTURE_IMAGE_MILK_AND_RICE", "FakeExtractor"]
