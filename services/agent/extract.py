"""Schema-bound text/image extraction (WP-05, P2's slice).

Per POA line 516, P2 supplies "schema-bound text/image extraction callable
through the agent contract" so P1's UI can show "here's what I understood"
for confirmation instead of inventing its own parsing. See
`docs/specs/WP-05-extraction-contract-p2.md` for the full contract.

This module turns a raw transcript or image into WP-02 `Item`s:

1. Call the extraction port (`services.extraction`) for the requested mode
   -- the fake/dev backend or the real Bedrock one, never mixed.
2. Convert each `CandidateItem` into a real `Item`: a generated `item_id`, a
   canonical `Quantity` (rounded to base units, same non-truncating
   conversion WP-06's `compare.py` uses), and the flexibility/hard
   attributes exactly as the backend reported them -- never enriched,
   never guessed.
3. Enforce `MAX_ITEMS`: the first four resolved items pass through; anything
   beyond that is reported as `unresolved` with `reason_code=
   "item_limit_exceeded"`, never silently dropped.
4. A backend that cannot serve the request at all (`ExtractorUnavailable`)
   degrades to a single honest `unresolved` entry, never a failed call --
   the same "partial coverage, not a failed run" rule WP-06 applies to a
   merchant search failure.

Lives in `services.agent`, not `services.application`, for the same reason
as `compare.py`: it calls P2's own extraction backends directly.
"""

from __future__ import annotations

from datetime import datetime

from services.domain.ids import Record
from services.domain.intent import MAX_ITEMS, Flexibility, Item
from services.domain.units import Quantity, Unit, base_units_per, dimension_of

from services.application.ports import IdFactory
from services.extraction.base import ExtractorUnavailable
from services.extraction.models import CandidateItem, ExtractionResult, UnresolvedCandidate
from services.extraction.registry import build_extractor
from services.merchants.models import Mode


class UnresolvedExtraction(Record):
    """Something the extractor could not confidently turn into an `Item`.

    Deliberately a plain string `reason_code`, not a raw exception --
    `UnresolvedExtraction` is a pydantic `Record` and must round-trip to
    JSON, same reasoning as WP-06's `UnresolvedItem`.
    """

    raw_fragment: str
    reason_code: str
    reason_detail: str | None = None


class ExtractionOutcome(Record):
    """The full answer to one `/tasks/extract` call."""

    items: tuple[Item, ...]
    unresolved: tuple[UnresolvedExtraction, ...]


def _to_quantity(quantity_value: float, unit: str) -> Quantity | None:
    """Convert a candidate's raw quantity to base units without truncating.

    Same non-truncating rounding `compare.py::_to_quantity` uses for merchant
    pack sizes -- a fractional kg/l amount must not silently become zero.
    """
    try:
        domain_unit = Unit(unit)
    except ValueError:
        return None
    value_base = round(quantity_value * base_units_per(domain_unit))
    if value_base <= 0:
        return None
    return Quantity(value_base=value_base, dimension=dimension_of(domain_unit))


def _candidate_to_item(
    candidate: CandidateItem, id_factory: IdFactory
) -> Item | UnresolvedExtraction:
    quantity = _to_quantity(candidate.quantity_value, candidate.unit)
    if quantity is None:
        return UnresolvedExtraction(
            raw_fragment=candidate.raw_fragment,
            reason_code="no_quantity_detected",
            reason_detail=f"could not represent {candidate.quantity_value} {candidate.unit!r}",
        )
    try:
        flexibility = Flexibility(candidate.flexibility)
    except ValueError:
        flexibility = Flexibility.EXACT_ONLY
    return Item(
        item_id=id_factory.new_id("item"),
        name=candidate.name,
        quantity=quantity,
        hard_attributes=dict(candidate.hard_attributes),
        flexibility=flexibility,
    )


def _unresolved_from_candidate(candidate: UnresolvedCandidate) -> UnresolvedExtraction:
    return UnresolvedExtraction(
        raw_fragment=candidate.raw_fragment,
        reason_code=candidate.reason_code,
        reason_detail=candidate.reason_detail,
    )


def _run_backend(
    mode: Mode,
    deadline: datetime,
    *,
    transcript: str | None,
    image_bytes: bytes | None,
    image_mime_type: str | None,
) -> ExtractionResult:
    extractor = build_extractor(mode)
    try:
        if transcript is not None:
            return extractor.extract_from_text(transcript, deadline)
        assert image_bytes is not None and image_mime_type is not None
        return extractor.extract_from_image(image_bytes, image_mime_type, deadline)
    except ExtractorUnavailable as exc:
        raw_fragment = transcript if transcript is not None else "<image>"
        return ExtractionResult(
            unresolved=(
                UnresolvedCandidate(
                    raw_fragment=raw_fragment,
                    reason_code="extraction_unavailable",
                    reason_detail=str(exc),
                ),
            )
        )


def run_extraction(
    *,
    mode: Mode,
    now: datetime,
    id_factory: IdFactory,
    transcript: str | None = None,
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
) -> ExtractionOutcome:
    """Extract items from exactly one of `transcript` or `image_bytes`.

    Callers (the `/tasks/extract` handler) validate that exactly one input is
    provided before calling this -- this function trusts that precondition
    and does not re-check it.
    """
    result = _run_backend(
        mode,
        now,
        transcript=transcript,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
    )

    items: list[Item] = []
    unresolved: list[UnresolvedExtraction] = [
        _unresolved_from_candidate(candidate) for candidate in result.unresolved
    ]

    for candidate in result.candidates:
        if len(items) >= MAX_ITEMS:
            unresolved.append(
                UnresolvedExtraction(
                    raw_fragment=candidate.raw_fragment,
                    reason_code="item_limit_exceeded",
                    reason_detail=f"at most {MAX_ITEMS} items are supported per request",
                )
            )
            continue
        resolved = _candidate_to_item(candidate, id_factory)
        if isinstance(resolved, Item):
            items.append(resolved)
        else:
            unresolved.append(resolved)

    return ExtractionOutcome(items=tuple(items), unresolved=tuple(unresolved))


__all__ = ["ExtractionOutcome", "UnresolvedExtraction", "run_extraction"]
