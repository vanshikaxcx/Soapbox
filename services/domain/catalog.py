"""Observations, matching and pack selection (WP-02).

An observation is what a merchant showed us at a moment in time, with the
locality it was verified for. Matching is deterministic and conservative:

- A missing or unknown attribute never satisfies a hard attribute. "We don't know
  whether this rice is basmati" is not "yes".
- A brand or pack change happens only where the shopper's flexibility permits it,
  and is always recorded on the line rather than silently applied.
- Pack selection minimises total quantity first, then cost, then pack count, with
  a lexicographic SKU tie-break, so the same inputs always give the same basket.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from services.domain.errors import (
    HardAttributeUnsatisfied,
    IncompatibleUnits,
    OverbuyLimitExceeded,
    SubstitutionNotPermitted,
)
from services.domain.ids import Id, Mode, Record, Timestamped
from services.domain.intent import Item
from services.domain.money import Money
from services.domain.units import Quantity

#: Overbuy ceiling in integer basis points: 15000 bp = 1.5x the requested amount.
#: Basis points rather than a float, so the limit itself cannot introduce one.
OVERBUY_LIMIT_BP = 15_000
BP_DENOMINATOR = 10_000

#: A guard against a pathological search space. Real baskets are nowhere near it.
MAX_SEARCH_BASE_UNITS = 200_000


class ExtractionStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"


class Observation(Timestamped):
    """One merchant's answer about one product, at one place and time."""

    observation_id: Id
    merchant_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    pack: Quantity
    price: Money
    in_stock: bool
    verified_location: str = Field(min_length=1, max_length=200)
    fetched_at: datetime
    evidence_key: str | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.OK
    mode: Mode


class SubstitutionKind(StrEnum):
    BRAND = "brand"
    PACK = "pack"


class Substitution(Record):
    """A recorded, permitted departure from exactly what was asked for."""

    kind: SubstitutionKind
    requested: str
    supplied: str


# -- hard attributes -------------------------------------------------------


def satisfies_hard_attributes(
    item: Item, observation: Observation
) -> None | HardAttributeUnsatisfied:
    """None means every hard attribute is satisfied.

    Absence is never assent: an attribute the merchant did not publish, or
    published empty, fails.
    """
    for name, required in item.hard_attributes.items():
        observed = observation.attributes.get(name)
        if observed is None or observed == "" or observed != required:
            return HardAttributeUnsatisfied(
                attribute=name, required=required, observed=observed
            )
    return None


def check_substitution(
    item: Item, observation: Observation
) -> Substitution | None | SubstitutionNotPermitted:
    """Decide whether this observation is an allowed stand-in for the item.

    A brand change needs brand flexibility; a pack-size change needs pack
    flexibility. Returns the substitution to record, or None when nothing was
    substituted.
    """
    requested_brand = item.hard_attributes.get("brand")
    if (
        requested_brand is not None
        and observation.brand is not None
        and observation.brand != requested_brand
    ):
        if not item.flexibility.allows_brand_change:
            return SubstitutionNotPermitted(
                kind=SubstitutionKind.BRAND.value, flexibility=str(item.flexibility)
            )
        return Substitution(
            kind=SubstitutionKind.BRAND, requested=requested_brand, supplied=observation.brand
        )
    return None


# -- pack selection --------------------------------------------------------


class PackOption(Record):
    """One purchasable pack of a product."""

    sku: str
    pack: Quantity
    price: Money


class PackSelection(Record):
    """A deterministic choice of packs that meets the requirement."""

    counts: tuple[tuple[str, int], ...]  # (sku, count), sorted by sku
    total_quantity: Quantity
    total_price: Money
    overbuy_base_units: int
    pack_count: int


def _within_overbuy_limit(required_base: int, selected_base: int) -> bool:
    # selected / required <= limit_bp / 10000, in integers only.
    return selected_base * BP_DENOMINATOR <= required_base * OVERBUY_LIMIT_BP


def select_packs(
    required: Quantity, options: Sequence[PackOption]
) -> PackSelection | OverbuyLimitExceeded | IncompatibleUnits:
    """Choose packs to meet ``required``, minimising overbuy then cost.

    Ordering is total quantity, then total price, then pack count, then the SKU
    sequence -- fully deterministic, with no randomness and no dependence on the
    order the options arrived in.
    """
    if required.value_base <= 0:
        # Returning an empty selection here would quietly say "you need nothing,
        # that costs nothing". A zero-quantity requirement is a malformed request.
        raise ValueError("cannot select packs for a non-positive requirement")

    if not options:
        return OverbuyLimitExceeded(
            required_base_units=required.value_base,
            selected_base_units=0,
            limit_bp=OVERBUY_LIMIT_BP,
        )

    for option in options:
        if option.pack.dimension is not required.dimension:
            return IncompatibleUnits(
                from_dimension=option.pack.dimension.value,
                to_dimension=required.dimension.value,
            )
        if option.pack.value_base <= 0:
            return IncompatibleUnits(
                from_dimension=required.dimension.value, to_dimension=required.dimension.value
            )

    need = required.value_base
    largest = max(option.pack.value_base for option in options)
    ceiling = need + largest
    if ceiling > MAX_SEARCH_BASE_UNITS:
        return OverbuyLimitExceeded(
            required_base_units=need, selected_base_units=ceiling, limit_bp=OVERBUY_LIMIT_BP
        )

    ordered = sorted(options, key=lambda o: o.sku)

    #: quantity -> (total paise, pack count, sku tuple)
    best: dict[int, tuple[int, int, tuple[str, ...]]] = {0: (0, 0, ())}
    for quantity in range(0, ceiling + 1):
        current = best.get(quantity)
        if current is None:
            continue
        cost, count, sequence = current
        for option in ordered:
            nxt = quantity + option.pack.value_base
            if nxt > ceiling:
                continue
            candidate = (cost + option.price.amount_paise, count + 1, sequence + (option.sku,))
            existing = best.get(nxt)
            if existing is None or candidate < existing:
                best[nxt] = candidate

    reachable = sorted(q for q in best if q >= need)
    if not reachable:
        return OverbuyLimitExceeded(
            required_base_units=need, selected_base_units=0, limit_bp=OVERBUY_LIMIT_BP
        )

    chosen_quantity = reachable[0]
    cost, count, sequence = best[chosen_quantity]
    overbuy = chosen_quantity - need

    if not _within_overbuy_limit(need, chosen_quantity):
        return OverbuyLimitExceeded(
            required_base_units=need,
            selected_base_units=chosen_quantity,
            limit_bp=OVERBUY_LIMIT_BP,
        )

    counts: dict[str, int] = {}
    for sku in sequence:
        counts[sku] = counts.get(sku, 0) + 1

    return PackSelection(
        counts=tuple(sorted(counts.items())),
        total_quantity=Quantity(value_base=chosen_quantity, dimension=required.dimension),
        total_price=Money.paise(cost),
        overbuy_base_units=overbuy,
        pack_count=count,
    )


def is_usable(observation: Observation) -> bool:
    """A stocked observation we actually managed to read."""
    return observation.in_stock and observation.extraction_status in (
        ExtractionStatus.OK,
        ExtractionStatus.PARTIAL,
    )


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "BP_DENOMINATOR",
    "ExtractionStatus",
    "MAX_SEARCH_BASE_UNITS",
    "OVERBUY_LIMIT_BP",
    "Observation",
    "PackOption",
    "PackSelection",
    "Substitution",
    "SubstitutionKind",
    "check_substitution",
    "is_usable",
    "satisfies_hard_attributes",
    "select_packs",
]
