"""Raw, pre-domain-schema extraction results (WP-05, P2's slice).

These are backend-internal shapes, not WP-02 records: a backend (fake or
Bedrock) only knows raw text/units/attributes as words, not a validated
canonical `Quantity` or a generated `item_id`. `services.agent.extract`
converts a `CandidateItem` into a real WP-02 `Item`; these types never leave
`services.extraction`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CandidateItem:
    """One item a backend is confident enough to hand to the domain schema.

    `unit` is one of `services.domain.units.Unit`'s string values ("g", "kg",
    "ml", "l", "piece") -- backends must already have resolved a unit alias
    to this set, never a raw word like "kgs".
    """

    raw_fragment: str
    name: str
    quantity_value: float
    unit: str
    hard_attributes: dict[str, str] = field(default_factory=dict)
    flexibility: str = "exact_only"


@dataclass(frozen=True, slots=True)
class UnresolvedCandidate:
    """Something the backend could not confidently turn into an item."""

    raw_fragment: str
    reason_code: str
    reason_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """A backend's full answer to one `extract_from_text`/`extract_from_image` call."""

    candidates: tuple[CandidateItem, ...] = ()
    unresolved: tuple[UnresolvedCandidate, ...] = ()


__all__ = ["CandidateItem", "ExtractionResult", "UnresolvedCandidate"]
