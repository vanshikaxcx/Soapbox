"""Search orchestration, basket assembly, fee integration and comparison (WP-06).

The gap WP-04 explicitly left open ("basket-level comparison, repair, ranking")
and WP-08's `prepare.py` explicitly defers ("re-selecting packs is WP-06's
job"). Lives in `services.agent`, not `services.application`: it calls P2's
own WP-04 connectors (`services.merchants`) directly and runs them
concurrently, and `services.application`'s boundary test forbids exactly
that (see `application/boundaries_test.py` -- that layer is P4's adapter
seam and must depend on nothing but the domain). This module is what turns
raw per-(merchant,item) observations into complete, comparable,
single-merchant baskets:

1. Map over (merchant, item) tasks at bounded concurrency, calling P2's WP-04
   connectors directly.
2. Convert each connector's raw ``Observation`` into WP-02's domain
   ``Observation`` -- including the brand extraction WP-04 deliberately left
   at ``attributes={}`` ("hard-attribute extraction isn't built (WP-06
   scope)", see ``p3_merchant_port_adapter.py``).
3. For each item, resolve the cheapest permitted match on each merchant: an
   exact match if one exists, otherwise the cheapest permitted substitution
   -- never a forbidden one, and never a guess when nothing qualifies. This
   is the "bounded repair": bounded by the item's own declared flexibility,
   never a silent constraint relaxation.
4. Assess fees per merchant (via the connector's own published-policy
   estimate) and assemble a `Basket` per merchant whose totals are computed,
   never asserted.
5. Compare baskets with WP-02's `compare_baskets`/`cheapest`, honoring the
   budget constraint and the live/fixture isolation rule.

Every domain rule (matching, pack selection, honesty-safe comparison) lives in
`services.domain` and is only ever called here, never re-implemented -- WP-02
owns those rules, and duplicating one is exactly the kind of drift the other
packages' docstrings warn about.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from services.agent.config import ITEM_FETCH_DEADLINE_SECONDS, SEARCH_CONCURRENCY
from services.application.ports import IdFactory
from services.domain.basket import (
    Basket,
    BasketCost,
    BasketLine,
    build_basket,
    cheapest,
)
from services.domain.basket import (
    FeeAssessment as DomainFeeAssessment,
)
from services.domain.catalog import (
    ExtractionStatus as DomainExtractionStatus,
)
from services.domain.catalog import (
    Observation as DomainObservation,
)
from services.domain.catalog import (
    PackOption,
    Substitution,
    check_substitution,
    is_usable,
    satisfies_hard_attributes,
    select_packs,
)
from services.domain.errors import (
    BudgetExceeded,
    DomainError,
    MixedModeComparison,
    SubstitutionNotPermitted,
)
from services.domain.ids import Id, Record
from services.domain.ids import Mode as DomainMode
from services.domain.intent import Flexibility, Intent, Item
from services.domain.keys import line_hash
from services.domain.money import (
    Amount,
    BudgetCheck,
    Charge,
    ChargeKind,
    Confidence,
    Money,
    check_budget,
)
from services.domain.units import Dimension, Quantity, Unit, base_units_per, dimension_of
from services.merchants.base import Merchant
from services.merchants.models import ExtractionStatus as RawExtractionStatus
from services.merchants.models import FeeAssessment as RawFeeAssessment
from services.merchants.models import ItemQuery, Location
from services.merchants.models import Line as RawLine
from services.merchants.models import Mode as RawMode
from services.merchants.models import Observation as RawObservation
from services.merchants.registry import build_registry

_UNIT_MAP: dict[str, Unit] = {
    "kg": Unit.KG,
    "g": Unit.G,
    "l": Unit.L,
    "ml": Unit.ML,
    "pack": Unit.PIECE,
    "pcs": Unit.PIECE,
}

_EXTRACTION_STATUS_MAP: dict[RawExtractionStatus, DomainExtractionStatus] = {
    RawExtractionStatus.OK: DomainExtractionStatus.OK,
    RawExtractionStatus.PARTIAL: DomainExtractionStatus.PARTIAL,
    RawExtractionStatus.BLOCKED: DomainExtractionStatus.BLOCKED,
    # Neither connector emits a distinct "not found" vs "error" signal that the
    # domain taxonomy cares about; both collapse to FAILED.
    RawExtractionStatus.NOT_FOUND: DomainExtractionStatus.FAILED,
    RawExtractionStatus.ERROR: DomainExtractionStatus.FAILED,
}

_DIMENSION_QUERY_UNIT: dict[Dimension, str] = {
    Dimension.MASS: "g",
    Dimension.VOLUME: "ml",
    Dimension.COUNT: "pack",
}

_FLEXIBILITY_QUERY: dict[Flexibility, str] = {
    Flexibility.EXACT_ONLY: "strict",
    Flexibility.BRAND_FLEXIBLE: "brand_flexible",
    Flexibility.PACK_FLEXIBLE: "pack_flexible",
    # The raw connector's ItemQuery only distinguishes three flexibility
    # strings and neither connector currently reads this field at all
    # (confirmed: no reference to `item.flexibility` in blinkit.py/zepto.py).
    # brand_flexible is the closer of the two single-axis strings to convey.
    Flexibility.BRAND_AND_PACK_FLEXIBLE: "brand_flexible",
}


def _observation_id(merchant_id: str, sku: str) -> str:
    """A stable, `Id`-pattern-valid identifier for a (merchant, sku) pair.

    Real SKUs (Zepto's, especially) contain slashes and are not guaranteed to
    match WP-02's `^[A-Za-z0-9_-]{8,64}$` pattern; a hash always does.
    """
    return hashlib.sha256(f"{merchant_id}:{sku}".encode()).hexdigest()[:32]


def _brand_of(product_name: str) -> str | None:
    """First capitalised alphabetic token, as a best-effort brand guess.

    Neither connector extracts a structured brand field (see WP-04's spec:
    "hard-attribute extraction isn't built (WP-06 scope)"), so this is a
    deliberately conservative heuristic over the free-text product name. It
    only feeds `check_substitution`, which only fires when the shopper
    actually named a required brand -- a wrong guess here can cause a
    spurious substitution record on a line, never a silently wrong price or
    a hard-attribute rule bypass (that path only ever reads `attributes`,
    which this converter leaves empty; absence is never assent).
    """
    for token in product_name.split():
        cleaned = token.strip(",.()-")
        if cleaned.isalpha() and cleaned[:1].isupper():
            return cleaned
    return None


def _to_quantity(pack_size: float, unit: str) -> Quantity | None:
    """Convert a parsed pack size to base units without truncating.

    `pack_size` is a float (`parse_pack_size` returns "0.5" for "500 g"
    listed as "0.5 kg", for instance); rounding to the base unit of its own
    dimension keeps a fractional kg/l pack from silently becoming zero.
    """
    domain_unit = _UNIT_MAP.get(unit)
    if domain_unit is None:
        return None
    value_base = round(pack_size * base_units_per(domain_unit))
    if value_base <= 0:
        return None
    return Quantity(value_base=value_base, dimension=dimension_of(domain_unit))


def to_domain_observation(raw: RawObservation) -> DomainObservation | None:
    """Convert one connector observation into WP-02's domain shape.

    Returns ``None`` for a card whose unit or pack size this package cannot
    represent -- treated as if the merchant simply hadn't shown that product,
    never as a whole-search failure.
    """
    quantity = _to_quantity(raw.pack_size, raw.unit)
    if quantity is None:
        return None
    return DomainObservation(
        observation_id=_observation_id(raw.merchant, raw.sku),
        merchant_id=raw.merchant,
        sku=raw.sku,
        url=raw.url,
        name=raw.product_name,
        brand=_brand_of(raw.product_name),
        attributes={},
        pack=quantity,
        price=Money.paise(raw.price_paise),
        in_stock=raw.in_stock,
        verified_location=raw.verified_location.pincode,
        fetched_at=raw.fetch_time,
        evidence_key=raw.evidence_key,
        extraction_status=_EXTRACTION_STATUS_MAP[raw.extraction_status],
        mode=DomainMode.LIVE if raw.mode is RawMode.LIVE else DomainMode.FIXTURE,
    )


#: A bare size/quantity token embedded in a product name (e.g. "1kg", "500 g"
#: split into two tokens, "5l") -- stripped before building a product-group
#: key, since real listings routinely put the pack size directly in the name
#: ("Fortune Sunflower Oil 1 L") and two pack sizes of one product must group
#: together for pack-combination, not split apart because their names differ
#: only in that size text.
_SIZE_TOKEN_RE = re.compile(r"^\d+(\.\d+)?(kg|g|gm|gms|ml|l|ltr|litre|litres|pcs?|pack s?)?$")


def _product_key(observation: DomainObservation) -> str:
    """Group observations that are different pack sizes of the same product.

    Deterministic and conservative: brand plus the three leading non-size
    name tokens (after dropping a leading brand token so it isn't double
    counted). Two genuinely different products that happen to share this
    signature would wrongly combine into one pack-selection group -- a real
    limitation of text-only matching with no structured product ID, accepted
    for the hackathon's two-merchant, four-item scope.
    """
    brand = (observation.brand or "").strip().lower()
    tokens = [
        cleaned
        for raw_token in observation.name.split()
        if (cleaned := raw_token.strip(",.()").lower()) and not _SIZE_TOKEN_RE.match(cleaned)
    ]
    if tokens and brand and tokens[0] == brand:
        tokens = tokens[1:]
    return f"{brand}|{' '.join(tokens[:3])}"


class UnresolvedItem(Record):
    """One item that could not be completed on one merchant, and why."""

    item_id: Id
    name: str
    reason_code: str
    reason_detail: str = ""


def _unresolved(item: Item, error: DomainError | str) -> UnresolvedItem:
    if isinstance(error, DomainError):
        return UnresolvedItem(
            item_id=item.item_id, name=item.name, reason_code=error.code, reason_detail=repr(error)
        )
    return UnresolvedItem(item_id=item.item_id, name=item.name, reason_code=error)


def resolve_item_for_merchant(
    *, item: Item, merchant_id: str, observations: Sequence[DomainObservation]
) -> BasketLine | UnresolvedItem:
    """Match one item against one merchant's observations, with bounded repair.

    "Bounded" means: every candidate this considers is either an exact match
    or a substitution the item's own `Flexibility` already permits (checked
    by WP-02's `check_substitution`), and pack combinations never exceed
    WP-02's overbuy ceiling. Nothing here ever relaxes a constraint the
    shopper didn't already agree to relax.

    Preference order is deterministic: exact matches before substituted ones,
    then by product-group key -- so the same inputs always yield the same
    basket, never a basket that depends on connector result ordering.
    """
    usable = [o for o in observations if o.merchant_id == merchant_id and is_usable(o)]
    if not usable:
        return _unresolved(item, "no_results")

    groups: dict[str, list[DomainObservation]] = {}
    for observation in usable:
        groups.setdefault(_product_key(observation), []).append(observation)

    # `brand` has its own field/substitution pathway (`check_substitution`,
    # via `observation.brand`); `satisfies_hard_attributes` reads
    # `observation.attributes`, a disjoint dict this package never populates
    # with brand. Checking both would make *every* brand-attributed item fail
    # here first, before substitution ever gets a chance to run.
    non_brand_attributes = {k: v for k, v in item.hard_attributes.items() if k != "brand"}
    non_brand_item = (
        item.model_copy(update={"hard_attributes": non_brand_attributes})
        if "brand" in item.hard_attributes
        else item
    )

    candidates: list[tuple[list[DomainObservation], Substitution | None]] = []
    fallback: DomainError | str = "no_results"
    for key in sorted(groups):
        group = groups[key]
        representative = group[0]
        hard_failure = satisfies_hard_attributes(non_brand_item, representative)
        if hard_failure is not None:
            fallback = hard_failure
            continue
        substitution = check_substitution(item, representative)
        if isinstance(substitution, SubstitutionNotPermitted):
            fallback = substitution
            continue
        candidates.append((group, substitution))

    # Stable sort: exact matches (substitution is None) before substituted
    # ones, preserving the deterministic group-key order within each tier.
    candidates.sort(key=lambda c: c[1] is not None)

    for group, substitution in candidates:
        options = [PackOption(sku=o.sku, pack=o.pack, price=o.price) for o in group]
        selection = select_packs(item.quantity, options)
        if isinstance(selection, DomainError):
            fallback = selection
            continue

        by_sku = {o.sku: o for o in group}
        rep_sku = max(selection.counts, key=lambda c: c[1])[0]
        rep_observation = by_sku[rep_sku]
        return BasketLine(
            item_id=item.item_id,
            observation_id=rep_observation.observation_id,
            merchant_id=merchant_id,
            sku=rep_sku,
            name=rep_observation.name,
            pack_counts=selection.counts,
            selected_base_units=selection.total_quantity.value_base,
            pack_base_units=rep_observation.pack.value_base,
            dimension=selection.total_quantity.dimension.value,
            overbuy_base_units=selection.overbuy_base_units,
            substitution=substitution,
            unit_price=rep_observation.price,
            line_total=Amount.known(selection.total_price),
        )

    return _unresolved(item, fallback)


class MerchantResult(Record):
    """How one merchant went: a complete basket, or what blocked one."""

    merchant_id: str
    basket: Basket | None = None
    unresolved: tuple[UnresolvedItem, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.basket is not None


class ComparisonOutcome(Record):
    """The result of one comparison run: every merchant's outcome, and the winner."""

    search_id: Id
    intent_id: Id
    intent_revision: int
    mode: DomainMode
    location: str
    results: tuple[MerchantResult, ...]
    winner_merchant_id: str | None = None
    budget_check: str = BudgetCheck.UNKNOWN.value


def _domain_charge(kind: ChargeKind, amount_paise: int | None, confidence: Confidence) -> Charge:
    # A fee the merchant didn't report at all (e.g. Blinkit's platform fee --
    # fees.py deliberately returns None for it) is unknown, never zero.
    # Dropping it here would let `compute_totals` silently treat an unpriced
    # fee as if it didn't exist -- confirmed live: Blinkit's real
    # platform_fee_paise=None was disappearing instead of making the total's
    # confidence UNKNOWN. See `docs/specs/WP-06-search-comparison-basket-
    # repair.md`'s addendum for the live check that found this.
    if amount_paise is None or confidence is Confidence.UNKNOWN:
        return Charge.unknown_charge(kind)
    return Charge.known_charge(kind, Money.paise(amount_paise), confidence)


def to_domain_fee_assessment(
    raw: RawFeeAssessment, *, location: str, lines: Sequence[BasketLine], assessed_at: datetime
) -> DomainFeeAssessment:
    """Convert a connector's raw fee estimate into WP-02's bound `FeeAssessment`.

    `line_hash` is WP-02's real domain-separated hash over the exact lines
    it was quoted for -- not the local placeholder `fees.placeholder_line_hash`
    the connectors themselves fall back to, which predates WP-02 landing in
    this tree.
    """
    confidence = (
        Confidence.VERIFIED
        if raw.completeness == "complete"
        else Confidence.UNKNOWN
        if raw.completeness == "unknown"
        else Confidence.ESTIMATED
    )
    charges = (
        _domain_charge(ChargeKind.DELIVERY, raw.delivery_fee_paise, confidence),
        _domain_charge(ChargeKind.OTHER, raw.platform_fee_paise, confidence),
        _domain_charge(ChargeKind.HANDLING, raw.other_fees_paise, confidence),
    )
    return DomainFeeAssessment(
        merchant_id=raw.merchant,
        location=location,
        line_hash=line_hash(list(lines)),
        subtotal=Money.paise(raw.subtotal_paise),
        assessed_at=assessed_at,
        charges=tuple(charges),
    )


def _assess_and_build(
    *,
    merchant: Merchant,
    merchant_id: str,
    search_id: str,
    location: Location,
    mode: DomainMode,
    lines: list[BasketLine],
    now: datetime,
    deadline_seconds: int,
    basket_id: str,
) -> Basket:
    """Assess fees for a resolved set of lines and assemble the merchant's basket.

    Each domain line becomes one raw `Line` with `quantity=1`: the connector's
    own subtotal formula is `price_paise * quantity`, and each line's true
    total (from WP-02's pack selection, which already knows every candidate
    SKU's price) is exactly that -- passing per-SKU pack counts through again
    would double-apply pricing this package already resolved.
    """
    raw_lines = [
        RawLine(sku=line.sku, quantity=1.0, price_paise=line.line_total.amount.amount_paise)
        for line in lines
        if line.line_total.amount is not None
    ]
    deadline = now + timedelta(seconds=deadline_seconds)
    raw_assessment = merchant.assess_fees(location, raw_lines, deadline)
    fee_assessment = (
        to_domain_fee_assessment(
            raw_assessment, location=location.pincode, lines=lines, assessed_at=now
        )
        if raw_assessment is not None
        else None
    )
    return build_basket(
        basket_id=basket_id,
        search_id=search_id,
        merchant_id=merchant_id,
        mode=mode,
        lines=tuple(lines),
        fee_assessment=fee_assessment,
    )


def _pick_winner(
    results: Sequence[MerchantResult], budget_paise: int | None
) -> tuple[str | None, str]:
    """The cheapest complete, in-budget basket -- or an honest reason there isn't one."""
    complete = [r for r in results if r.basket is not None]
    if not complete:
        return None, BudgetCheck.UNKNOWN.value

    if budget_paise is not None:
        pool = [
            r
            for r in complete
            if r.basket is not None
            and not isinstance(check_budget(r.basket.totals, budget_paise), BudgetExceeded)
        ]
        if not pool:
            return None, BudgetCheck.EXCEEDED.value
    else:
        pool = complete

    costs = [
        BasketCost(basket_id=r.basket.basket_id, mode=r.basket.mode, totals=r.basket.totals)
        for r in pool
        if r.basket is not None
    ]
    verdict = cheapest(costs)
    status = BudgetCheck.WITHIN.value if budget_paise is not None else BudgetCheck.UNKNOWN.value
    if verdict is None or isinstance(verdict, MixedModeComparison):
        return None, status
    winner = next(
        r for r in pool if r.basket is not None and r.basket.basket_id == verdict.basket_id
    )
    return winner.merchant_id, status


def _query_for(item: Item) -> ItemQuery:
    unit = _DIMENSION_QUERY_UNIT[item.quantity.dimension]
    return ItemQuery(
        name=item.name,
        quantity=float(item.quantity.value_base),
        unit=unit,
        hard_attributes=dict(item.hard_attributes),
        flexibility=_FLEXIBILITY_QUERY[item.flexibility],
    )


def run_comparison(
    *,
    intent: Intent,
    location: Location,
    mode: DomainMode,
    now: datetime,
    id_factory: IdFactory,
    registry: dict[str, Merchant] | None = None,
    deadline_seconds: int = ITEM_FETCH_DEADLINE_SECONDS,
) -> ComparisonOutcome:
    """Search every registered merchant for every item, then compare.

    One `search_id` covers the whole run. Each (merchant, item) task is
    independent -- a failure or an unmatchable item on one merchant never
    blocks another merchant's basket (SPEC section 1: partial coverage, not a
    failed search) -- and the whole run is bounded to `SEARCH_CONCURRENCY`
    tasks in flight, per the POA.
    """
    live_registry = registry if registry is not None else build_registry(RawMode(mode.value))
    deadline = now + timedelta(seconds=deadline_seconds)

    tasks = [
        (merchant_id, merchant, item)
        for merchant_id, merchant in live_registry.items()
        for item in intent.items
    ]
    observations: dict[tuple[str, str], list[DomainObservation]] = {}
    with ThreadPoolExecutor(max_workers=max(SEARCH_CONCURRENCY, 1)) as executor:
        futures = {
            executor.submit(merchant.search, location, _query_for(item), deadline): (
                merchant_id,
                item.item_id,
            )
            for merchant_id, merchant, item in tasks
        }
        for future, (merchant_id, item_id) in futures.items():
            outcome = future.result()
            converted: list[DomainObservation] = []
            # A typed MerchantError yields zero observations here -- surfaced
            # per item below, never as a whole-search failure.
            if isinstance(outcome, list):
                for raw in outcome:
                    domain_observation = to_domain_observation(raw)
                    if domain_observation is not None:
                        converted.append(domain_observation)
            observations[(merchant_id, item_id)] = converted

    search_id = id_factory.new_id("search")
    results: list[MerchantResult] = []
    for merchant_id, merchant in live_registry.items():
        lines: list[BasketLine] = []
        unresolved: list[UnresolvedItem] = []
        for item in intent.items:
            resolution = resolve_item_for_merchant(
                item=item,
                merchant_id=merchant_id,
                observations=observations.get((merchant_id, item.item_id), []),
            )
            if isinstance(resolution, BasketLine):
                lines.append(resolution)
            else:
                unresolved.append(resolution)

        if unresolved:
            results.append(MerchantResult(merchant_id=merchant_id, unresolved=tuple(unresolved)))
            continue

        basket = _assess_and_build(
            merchant=merchant,
            merchant_id=merchant_id,
            search_id=search_id,
            location=location,
            mode=mode,
            lines=lines,
            now=now,
            deadline_seconds=deadline_seconds,
            basket_id=id_factory.new_id("basket"),
        )
        results.append(MerchantResult(merchant_id=merchant_id, basket=basket))

    winner_merchant_id, budget_check = _pick_winner(results, intent.budget_paise)
    return ComparisonOutcome(
        search_id=search_id,
        intent_id=intent.intent_id,
        intent_revision=intent.revision,
        mode=mode,
        location=intent.location,
        results=tuple(results),
        winner_merchant_id=winner_merchant_id,
        budget_check=budget_check,
    )


__all__ = [
    "ITEM_FETCH_DEADLINE_SECONDS",
    "SEARCH_CONCURRENCY",
    "ComparisonOutcome",
    "MerchantResult",
    "UnresolvedItem",
    "resolve_item_for_merchant",
    "run_comparison",
    "to_domain_fee_assessment",
    "to_domain_observation",
]
