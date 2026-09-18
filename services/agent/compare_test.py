"""WP-06: search orchestration, basket assembly and comparison.

Exercises the whole path against fake `Merchant` connectors (the same ABC
WP-04's Blinkit/Zepto/Fixture connectors implement) so these tests never touch
a real browser or network call -- only the orchestration and domain wiring
this package owns.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services.agent.compare import (
    ComparisonOutcome,
    UnresolvedItem,
    resolve_item_for_merchant,
    run_comparison,
    to_domain_observation,
)
from services.application.fakes import SequentialIds
from services.domain.basket import BasketLine
from services.domain.errors import DomainError
from services.domain.ids import Mode
from services.domain.intent import Flexibility, Intent, Item
from services.domain.money import BudgetCheck
from services.domain.units import Quantity, Unit
from services.merchants.base import Merchant
from services.merchants.models import ExtractionStatus as RawExtractionStatus
from services.merchants.models import FeeAssessment as RawFeeAssessment
from services.merchants.models import ItemQuery, Location, MerchantError, MerchantErrorCode
from services.merchants.models import Line as RawLine
from services.merchants.models import Mode as RawMode
from services.merchants.models import Observation as RawObservation

NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
LOCATION = Location(locality="Connaught Place", pincode="110001")
OWNER = "owner-0001"


def raw_observation(
    *,
    merchant: str,
    sku: str,
    name: str,
    price_paise: int,
    pack_size: float = 5.0,
    unit: str = "kg",
    in_stock: bool = True,
) -> RawObservation:
    return RawObservation(
        merchant=merchant,
        sku=sku,
        url=f"https://{merchant}.example/{sku}",
        product_name=name,
        pack_size=pack_size,
        unit=unit,
        price_paise=price_paise,
        in_stock=in_stock,
        verified_location=LOCATION,
        fetch_time=NOW,
        evidence_key="evidence-key",
        extraction_status=RawExtractionStatus.OK,
        mode=RawMode.LIVE,
    )


def an_item(
    *,
    item_id: str = "item-00001",
    name: str = "rice",
    quantity: Quantity | None = None,
    hard_attributes: dict[str, str] | None = None,
    flexibility: Flexibility = Flexibility.EXACT_ONLY,
) -> Item:
    return Item(
        item_id=item_id,
        name=name,
        quantity=quantity if quantity is not None else Quantity.of(5, Unit.KG),
        hard_attributes=hard_attributes or {},
        flexibility=flexibility,
    )


def an_intent(
    *, items: tuple[Item, ...], budget_paise: int | None = None, intent_id: str = "intent-0001"
) -> Intent:
    return Intent(
        intent_id=intent_id,
        owner_id=OWNER,
        items=items,
        location="Connaught Place, New Delhi",
        budget_paise=budget_paise,
    )


class FakeMerchant(Merchant):
    """A `Merchant` connector that answers from a script -- WP-04's connectors
    are verified separately; this stands in for one behind the same port."""

    def __init__(
        self,
        name: str,
        *,
        catalog: dict[str, list[RawObservation] | MerchantError] | None = None,
        fee: RawFeeAssessment | None = None,
    ) -> None:
        self.name = name
        self._catalog = catalog or {}
        self._fee = fee
        self.search_calls: list[str] = []
        self.assess_fees_calls: list[list[RawLine]] = []

    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[RawObservation] | MerchantError:
        self.search_calls.append(item.name)
        return self._catalog.get(item.name, [])

    def refresh(self, location: Location, sku: str, deadline: datetime) -> RawObservation:
        raise NotImplementedError("not exercised by WP-06")

    def assess_fees(
        self, location: Location, exact_lines: list[RawLine], deadline: datetime
    ) -> RawFeeAssessment | None:
        self.assess_fees_calls.append(exact_lines)
        return self._fee


def fee(merchant: str, *, subtotal_paise: int, delivery_paise: int | None = 0) -> RawFeeAssessment:
    # platform/other default to a known 0, not None: None means "this fee was
    # never assessed at all", which correctly makes the whole total UNKNOWN
    # (see test_two_estimated_baskets_are_not_comparable-style honesty rule)
    # -- these two are known-zero fees for tests that aren't about that rule.
    return RawFeeAssessment(
        merchant=merchant,
        location=LOCATION,
        line_hash="irrelevant",
        subtotal_paise=subtotal_paise,
        delivery_fee_paise=delivery_paise,
        platform_fee_paise=0,
        other_fees_paise=0,
        completeness="estimated",
        fetch_time=NOW,
    )


# -- to_domain_observation ---------------------------------------------------


def test_to_domain_observation_converts_fractional_pack_size_without_truncating() -> None:
    raw = raw_observation(
        merchant="blinkit",
        sku="sku-1",
        name="Fortune Basmati Rice",
        price_paise=25_000,
        pack_size=0.5,
        unit="kg",
    )
    converted = to_domain_observation(raw)
    assert converted is not None
    assert converted.pack.value_base == 500  # not truncated to 0
    assert converted.brand == "Fortune"


def test_to_domain_observation_rejects_unmapped_unit() -> None:
    raw = raw_observation(merchant="blinkit", sku="sku-1", name="X", price_paise=100, unit="dozen")
    assert to_domain_observation(raw) is None


# -- resolve_item_for_merchant -----------------------------------------------


def test_resolve_item_picks_the_sku_that_meets_quantity_at_least_cost() -> None:
    item = an_item(quantity=Quantity.of(5, Unit.KG))
    observations = [
        to_domain_observation(
            raw_observation(
                merchant="blinkit",
                sku="rice-1kg",
                name="Fortune Rice 1kg",
                price_paise=12_000,
                pack_size=1.0,
                unit="kg",
            )
        ),
        to_domain_observation(
            raw_observation(
                merchant="blinkit",
                sku="rice-5kg",
                name="Fortune Rice 5kg",
                price_paise=55_000,
                pack_size=5.0,
                unit="kg",
            )
        ),
    ]
    result = resolve_item_for_merchant(
        item=item, merchant_id="blinkit", observations=[o for o in observations if o]
    )
    assert isinstance(result, BasketLine)
    assert result.sku == "rice-5kg"
    assert result.selected_base_units == 5000
    assert result.overbuy_base_units == 0
    assert result.substitution is None


def test_resolve_item_reports_no_results_when_nothing_in_stock() -> None:
    item = an_item()
    observations = [
        to_domain_observation(
            raw_observation(
                merchant="blinkit",
                sku="rice-1",
                name="Fortune Rice",
                price_paise=10_000,
                in_stock=False,
            )
        )
    ]
    result = resolve_item_for_merchant(
        item=item, merchant_id="blinkit", observations=[o for o in observations if o]
    )
    assert isinstance(result, UnresolvedItem)
    assert result.reason_code == "no_results"


def test_resolve_item_never_returns_a_forbidden_brand_substitution() -> None:
    item = an_item(hard_attributes={"brand": "Fortune"}, flexibility=Flexibility.EXACT_ONLY)
    observations = [
        to_domain_observation(
            raw_observation(
                merchant="blinkit", sku="rice-tata", name="Tata Sampann Rice", price_paise=48_000
            )
        )
    ]
    result = resolve_item_for_merchant(
        item=item, merchant_id="blinkit", observations=[o for o in observations if o]
    )
    assert isinstance(result, UnresolvedItem)
    assert result.reason_code == "substitution_not_permitted"


def test_resolve_item_records_a_permitted_brand_substitution() -> None:
    item = an_item(hard_attributes={"brand": "Fortune"}, flexibility=Flexibility.BRAND_FLEXIBLE)
    observations = [
        to_domain_observation(
            raw_observation(
                merchant="blinkit", sku="rice-tata", name="Tata Sampann Rice", price_paise=48_000
            )
        )
    ]
    result = resolve_item_for_merchant(
        item=item, merchant_id="blinkit", observations=[o for o in observations if o]
    )
    assert isinstance(result, BasketLine)
    assert result.substitution is not None
    assert result.substitution.requested == "Fortune"
    assert result.substitution.supplied == "Tata"


def test_resolve_item_prefers_exact_match_over_substitution() -> None:
    item = an_item(hard_attributes={"brand": "Fortune"}, flexibility=Flexibility.BRAND_FLEXIBLE)
    observations = [
        to_domain_observation(
            raw_observation(
                merchant="blinkit", sku="rice-tata", name="Tata Sampann Rice", price_paise=40_000
            )
        ),
        to_domain_observation(
            raw_observation(
                merchant="blinkit",
                sku="rice-fortune",
                name="Fortune Basmati Rice",
                price_paise=60_000,
            )
        ),
    ]
    result = resolve_item_for_merchant(
        item=item, merchant_id="blinkit", observations=[o for o in observations if o]
    )
    assert isinstance(result, BasketLine)
    assert result.sku == "rice-fortune"
    assert result.substitution is None


# -- run_comparison -----------------------------------------------------------


def test_run_comparison_reports_no_definitive_winner_when_both_baskets_are_only_estimated() -> None:
    """The realistic case for two *live* merchants: WP-04's connectors always
    return a fee assessment labeled ``"estimated"``, never ``"complete"`` --
    so per WP-02's honesty rule (see `basket_test.py`'s
    `test_two_estimated_baskets_are_not_comparable`), neither basket's total
    can be proven cheaper than the other's, however large the price gap.
    Each basket's known subtotal is still reported for display; the
    comparison just refuses to call a winner it cannot prove.
    """
    item = an_item(name="rice", quantity=Quantity.of(5, Unit.KG))
    intent = an_intent(items=(item,))
    blinkit = FakeMerchant(
        "blinkit",
        catalog={
            "rice": [
                raw_observation(
                    merchant="blinkit", sku="b-rice", name="Fortune Rice", price_paise=90_000
                )
            ]
        },
        fee=fee("blinkit", subtotal_paise=90_000, delivery_paise=3_000),
    )
    zepto = FakeMerchant(
        "zepto",
        catalog={
            "rice": [
                raw_observation(
                    merchant="zepto", sku="z-rice", name="Fortune Rice", price_paise=48_000
                )
            ]
        },
        fee=fee("zepto", subtotal_paise=48_000, delivery_paise=0),
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit, "zepto": zepto},
    )
    assert isinstance(outcome, ComparisonOutcome)
    assert outcome.winner_merchant_id is None
    by_merchant = {r.merchant_id: r for r in outcome.results}
    assert by_merchant["blinkit"].is_complete
    assert by_merchant["zepto"].is_complete
    zepto_basket = by_merchant["zepto"].basket
    assert zepto_basket is not None
    assert zepto_basket.totals.known_subtotal.amount_paise == 48_000


def test_run_comparison_picks_a_winner_when_one_basket_has_no_open_charges() -> None:
    """A merchant whose fee lookup returned nothing at all (`assess_fees` ->
    `None`) contributes zero charges, so its total is exact (verified) --
    WP-02's comparator can then prove it cheaper than an estimated basket
    whose lower bound it beats.
    """
    item = an_item(name="rice", quantity=Quantity.of(5, Unit.KG))
    intent = an_intent(items=(item,))
    blinkit = FakeMerchant(
        "blinkit",
        catalog={
            "rice": [
                raw_observation(
                    merchant="blinkit", sku="b-rice", name="Fortune Rice", price_paise=40_000
                )
            ]
        },
        fee=None,
    )
    zepto = FakeMerchant(
        "zepto",
        catalog={
            "rice": [
                raw_observation(
                    merchant="zepto", sku="z-rice", name="Fortune Rice", price_paise=48_000
                )
            ]
        },
        fee=fee("zepto", subtotal_paise=48_000, delivery_paise=0),
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit, "zepto": zepto},
    )
    assert outcome.winner_merchant_id == "blinkit"


def test_a_fee_component_the_merchant_never_assessed_makes_the_total_unknown() -> None:
    """Confirmed live (2026-09-18): Blinkit's real `assess_fees` returns
    `platform_fee_paise=None` (unassessed, not zero -- see `fees.py`).
    Silently dropping that `None` from the charges list used to let the
    total compute as "estimated" with the platform fee missing entirely
    rather than accounted for. A basket with a truly unassessed fee
    component must never look more complete than it is.
    """
    item = an_item(name="rice", quantity=Quantity.of(5, Unit.KG))
    intent = an_intent(items=(item,))
    blinkit = FakeMerchant(
        "blinkit",
        catalog={
            "rice": [
                raw_observation(merchant="blinkit", sku="b-rice", name="Rice", price_paise=50_000)
            ]
        },
        fee=RawFeeAssessment(
            merchant="blinkit",
            location=LOCATION,
            line_hash="irrelevant",
            subtotal_paise=50_000,
            delivery_fee_paise=3_000,
            platform_fee_paise=None,  # never assessed -- not the same as zero
            completeness="estimated",
            fetch_time=NOW,
        ),
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit},
    )
    basket = outcome.results[0].basket
    assert basket is not None
    assert basket.totals.confidence == "unknown"
    assert basket.totals.total is None
    assert "other" in basket.totals.unknown_charges


def test_run_comparison_reports_partial_coverage_not_a_failed_search() -> None:
    item = an_item(name="rice")
    intent = an_intent(items=(item,))
    blinkit = FakeMerchant("blinkit", catalog={})  # nothing found
    zepto = FakeMerchant(
        "zepto",
        catalog={
            "rice": [
                raw_observation(merchant="zepto", sku="z-rice", name="Rice", price_paise=48_000)
            ]
        },
        fee=fee("zepto", subtotal_paise=48_000),
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit, "zepto": zepto},
    )
    by_merchant = {r.merchant_id: r for r in outcome.results}
    assert not by_merchant["blinkit"].is_complete
    assert by_merchant["blinkit"].unresolved[0].reason_code == "no_results"
    assert by_merchant["zepto"].is_complete
    assert outcome.winner_merchant_id == "zepto"


def test_run_comparison_excludes_a_basket_that_exceeds_budget() -> None:
    item = an_item(name="rice")
    intent = an_intent(items=(item,), budget_paise=45_000)
    blinkit = FakeMerchant(
        "blinkit",
        catalog={
            "rice": [
                raw_observation(merchant="blinkit", sku="b-rice", name="Rice", price_paise=50_000)
            ]
        },
        fee=fee("blinkit", subtotal_paise=50_000),
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit},
    )
    assert outcome.winner_merchant_id is None
    assert outcome.budget_check == BudgetCheck.EXCEEDED.value


def test_run_comparison_selects_the_cheaper_in_budget_basket_over_the_global_cheapest() -> None:
    """A globally cheaper basket that blows the budget must not blank out an
    affordable one -- the winner is the cheapest basket *within* budget."""
    item = an_item(name="rice")
    intent = an_intent(items=(item,), budget_paise=49_000)
    cheapest_but_over_budget = FakeMerchant(
        "blinkit",
        catalog={
            "rice": [
                raw_observation(merchant="blinkit", sku="b-rice", name="Rice", price_paise=40_000)
            ]
        },
        fee=fee("blinkit", subtotal_paise=40_000, delivery_paise=15_000),  # total 55,000
    )
    affordable = FakeMerchant(
        "zepto",
        catalog={
            "rice": [
                raw_observation(merchant="zepto", sku="z-rice", name="Rice", price_paise=48_000)
            ]
        },
        fee=fee("zepto", subtotal_paise=48_000, delivery_paise=0),  # total 48,000
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": cheapest_but_over_budget, "zepto": affordable},
    )
    assert outcome.winner_merchant_id == "zepto"
    assert outcome.budget_check == BudgetCheck.WITHIN.value


def test_run_comparison_calls_every_merchant_for_every_item() -> None:
    items = (an_item(item_id="item-00001", name="rice"), an_item(item_id="item-00002", name="oil"))
    intent = an_intent(items=items)
    blinkit = FakeMerchant(
        "blinkit",
        catalog={
            "rice": [
                raw_observation(merchant="blinkit", sku="b-rice", name="Rice", price_paise=50_000)
            ],
            "oil": [
                raw_observation(merchant="blinkit", sku="b-oil", name="Oil", price_paise=15_000)
            ],
        },
        fee=fee("blinkit", subtotal_paise=65_000),
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit},
    )
    assert sorted(blinkit.search_calls) == ["oil", "rice"]
    result = outcome.results[0]
    assert result.basket is not None
    assert len(result.basket.lines) == 2


def test_run_comparison_never_mixes_live_and_fixture_baskets_across_merchants() -> None:
    """Mode is bound per-run, not inferred from what the connector returns."""
    item = an_item(name="rice")
    intent = an_intent(items=(item,))
    blinkit = FakeMerchant(
        "blinkit",
        catalog={
            "rice": [
                raw_observation(merchant="blinkit", sku="b-rice", name="Rice", price_paise=50_000)
            ]
        },
        fee=fee("blinkit", subtotal_paise=50_000),
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.FIXTURE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit},
    )
    basket = outcome.results[0].basket
    assert basket is not None
    assert basket.mode is Mode.FIXTURE


def test_run_comparison_error_from_connector_is_partial_not_fatal() -> None:
    item = an_item(name="rice")
    intent = an_intent(items=(item,))
    blinkit = FakeMerchant(
        "blinkit",
        catalog={
            "rice": MerchantError(
                merchant="blinkit",
                code=MerchantErrorCode.TIMEOUT,
                message="timed out",
                occurred_at=NOW,
            )
        },
    )
    outcome = run_comparison(
        intent=intent,
        location=LOCATION,
        mode=Mode.LIVE,
        now=NOW,
        id_factory=SequentialIds(),
        registry={"blinkit": blinkit},
    )
    result = outcome.results[0]
    assert not result.is_complete
    assert result.unresolved[0].reason_code == "no_results"


def test_unresolved_item_never_carries_a_raw_domain_error_object() -> None:
    """UnresolvedItem is a Record (serializable); reasons must round-trip to JSON."""
    item = an_item()
    unresolved = resolve_item_for_merchant(item=item, merchant_id="blinkit", observations=[])
    assert isinstance(unresolved, UnresolvedItem)
    dumped = unresolved.model_dump(mode="json")
    assert isinstance(dumped["reason_code"], str)
    assert not isinstance(dumped["reason_code"], DomainError)
