"""The preparation half of WP-08 (acceptance criteria 6, 7, 8).

Criterion 7 is the one worth reading first: when a refresh fails, the price from
the original search must never be reused. It is the tempting shortcut, because
substituting it produces a confident, exact-looking total -- one that nobody has
verified.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.application.fakes import (
    AllowAllPolicy,
    FixedClock,
    MemoryStore,
    ScriptedMerchant,
    SequentialIds,
)
from services.application.ports import MerchantPort, read
from services.application.prepare import RefreshedFacts, build_quote, diff_between
from services.application.purchase import (
    AttemptCreated,
    PreparationAccepted,
    PurchaseUseCases,
    facts_key,
    purchase_key,
    quote_key,
)
from services.domain.basket import Basket, BasketLine, FeeAssessment, build_basket
from services.domain.catalog import Observation
from services.domain.errors import (
    DiffHashMismatch,
    DomainError,
    IncompatibleUnits,
    PreparationExpired,
    QuoteNotConstructible,
)
from services.domain.ids import Mode
from services.domain.money import Amount, Charge, ChargeKind, Confidence, Money
from services.domain.purchase import Diff, Preparation, Purchase
from services.domain.units import Quantity, Unit

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
OWNER = "owner-0001"
PURCHASE_ID = "purchase-0001"
LOCATION = "Indiranagar, Bengaluru"


def a_basket(*, paise: int = 58_000, delivery: int | None = 1_000) -> Basket:
    line = BasketLine(
        item_id="item-0001",
        observation_id="obs-00001",
        merchant_id="merchant-b",
        sku="rice-b",
        name="Basmati rice 5kg",
        pack_counts=(("rice-b", 1),),
        selected_base_units=5000,
        pack_base_units=5000,
        dimension="mass",
        unit_price=Money.paise(paise),
        line_total=Amount.known(Money.paise(paise)),
    )
    charge = (
        Charge.unknown_charge(ChargeKind.DELIVERY)
        if delivery is None
        else Charge.known_charge(ChargeKind.DELIVERY, Money.paise(delivery))
    )
    return build_basket(
        basket_id="basket-0001",
        search_id="search-0001",
        merchant_id="merchant-b",
        mode=Mode.LIVE,
        lines=(line,),
        fee_assessment=FeeAssessment(
            merchant_id="merchant-b",
            location=LOCATION,
            line_hash="a" * 64,
            subtotal=Money.paise(paise),
            assessed_at=NOW,
            charges=(charge,),
        ),
    )


def an_observation(sku: str, paise: int, *, in_stock: bool = True) -> Observation:
    return Observation(
        observation_id="obs-00002",
        merchant_id="merchant-b",
        sku=sku,
        url="https://merchant.example/p/1",
        name="Basmati rice 5kg",
        attributes={},
        pack=Quantity.of(5, Unit.KG),
        price=Money.paise(paise),
        in_stock=in_stock,
        verified_location=LOCATION,
        fetched_at=NOW,
        mode=Mode.LIVE,
    )


class World:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.clock = FixedClock(NOW)
        self.uc = PurchaseUseCases(
            store=self.store,
            clock=self.clock,
            ids=SequentialIds(),
            policy=AllowAllPolicy(),
        )
        self.purchase = Purchase(
            purchase_id=PURCHASE_ID,
            owner_id=OWNER,
            basket_id="basket-0001",
            intent_revision=1,
            mode=Mode.LIVE,
        )
        self.store.seed(purchase_key(PURCHASE_ID), self.purchase)

    def prepare(
        self, merchant: MerchantPort, basket: Basket | None = None
    ) -> tuple[Preparation, Diff] | DomainError:
        """Re-check, returning whatever the use case returned.

        Kept un-narrowed because the concurrency regressions import this World
        and rely on seeing the failure -- a second re-check landing on the same
        version must come back as ConditionFailed, not as an assertion error.
        """
        return self.uc.prepare(
            owner_id=OWNER,
            purchase_id=PURCHASE_ID,
            basket=basket or a_basket(),
            merchant=merchant,
            location=LOCATION,
        )

    def prepare_ok(
        self, merchant: MerchantPort, basket: Basket | None = None
    ) -> tuple[Preparation, Diff]:
        """Re-check, asserting it succeeded. For tests about what it produced."""
        result = self.prepare(merchant, basket)
        assert not isinstance(result, DomainError), f"prepare failed: {result}"
        return result

    def accept(self, diff_hash: str, version: int = 1) -> PreparationAccepted | DomainError:
        # Read the current version first, as a real client would: prepare
        # advances the purchase, so hard-coding 1 would be testing a stale client.
        current = self.purchase_row()
        return self.uc.accept_preparation(
            owner_id=OWNER,
            purchase_id=PURCHASE_ID,
            version=version,
            diff_hash=diff_hash,
            expected_purchase_version=current.version,
        )

    def accept_ok(self, diff_hash: str, version: int = 1) -> PreparationAccepted:
        """Accept, asserting it yielded a quote. For tests about the quote itself."""
        result = self.accept(diff_hash, version)
        assert not isinstance(result, DomainError), f"accept failed: {result}"
        return result

    def purchase_row(self) -> Purchase:
        # read() rather than store.get(): the typed helper is what production
        # uses, and it makes "the row is missing" a test failure here instead of
        # an AttributeError three lines later.
        found = read(self.store, purchase_key(PURCHASE_ID), Purchase)
        assert found is not None, "the purchase should exist"
        return found

    def current_version(self) -> int:
        return self.purchase_row().version

    def facts(self, version: int = 1) -> RefreshedFacts:
        found = read(self.store, facts_key(PURCHASE_ID, version), RefreshedFacts)
        assert found is not None, "refreshed facts should exist"
        return found


def merchant_selling(
    paise: int, *, in_stock: bool = True, fees: tuple[Charge, ...] | DomainError | None = None
) -> ScriptedMerchant:
    return ScriptedMerchant(
        observations={"rice-b": an_observation("rice-b", paise, in_stock=in_stock)},
        fees=fees
        if fees is not None
        else (Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
    )


# -- the refresh actually happens ------------------------------------------


def test_preparing_calls_the_merchant_for_every_line_and_once_for_fees() -> None:
    merchant = merchant_selling(58_000)
    World().prepare(merchant)
    assert merchant.refresh_calls == ["rice-b"]
    assert merchant.fee_calls == 1


def test_an_unchanged_basket_produces_an_empty_diff() -> None:
    world = World()
    preparation, diff = world.prepare_ok(merchant_selling(58_000))
    assert diff.changes == ()
    assert preparation.requires_acceptance is False


def test_a_price_rise_appears_as_one_typed_change() -> None:
    world = World()
    _prep, diff = world.prepare_ok(merchant_selling(59_500))
    prices = [c for c in diff.changes if c.kind.value == "price"]
    assert len(prices) == 1
    assert (prices[0].before, prices[0].after) == ("58000", "59500")


def test_a_fee_change_appears_as_its_own_change() -> None:
    world = World()
    _prep, diff = world.prepare_ok(
        merchant_selling(
            58_000, fees=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(3_000)),)
        )
    )
    fees = [c for c in diff.changes if c.kind.value == "fee"]
    assert len(fees) == 1
    assert (fees[0].before, fees[0].after) == ("1000", "3000")


def test_the_diff_hash_is_stable_across_identical_refreshes() -> None:
    first = World().prepare_ok(merchant_selling(59_500))[1]
    second = World().prepare_ok(merchant_selling(59_500))[1]
    assert first.hash() == second.hash()


# -- criterion 7: the stale price is never reused --------------------------


def test_a_failed_refresh_never_reuses_the_price_from_the_search() -> None:
    world = World()
    world.prepare(
        ScriptedMerchant(
            observations={
                "rice-b": IncompatibleUnits(from_dimension="mass", to_dimension="volume")
            },
            fees=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
        )
    )
    line = world.facts().lines[0]
    assert line.line_total.amount is None, "the stale Rs 580 must not reappear"
    assert line.unit_price is None
    assert line.failure_code == "incompatible_units"
    assert world.facts().totals().total is None


def test_an_out_of_stock_line_is_unpriced_rather_than_last_known_price() -> None:
    world = World()
    _prep, diff = world.prepare_ok(merchant_selling(58_000, in_stock=False))
    assert world.facts().lines[0].line_total.amount is None
    assert {c.kind.value for c in diff.changes} >= {"availability"}


def test_a_failed_fee_assessment_becomes_unknown_never_zero() -> None:
    world = World()
    world.prepare(
        merchant_selling(
            58_000, fees=IncompatibleUnits(from_dimension="mass", to_dimension="volume")
        )
    )
    charges = world.facts().charges
    assert charges and all(c.amount is None for c in charges)
    assert world.facts().totals().total is None


# -- acceptance and quote construction -------------------------------------


def test_a_diff_can_only_be_accepted_by_its_exact_hash() -> None:
    world = World()
    world.prepare(merchant_selling(59_500))
    assert isinstance(world.accept("0" * 64), DiffHashMismatch)


def test_accepting_a_fresh_diff_builds_a_quote_without_another_refresh() -> None:
    """The anti-loop rule, proven by the merchant's own call count."""
    world = World()
    merchant = merchant_selling(59_500)
    _prep, diff = world.prepare_ok(merchant)
    calls_after_prepare = len(merchant.refresh_calls)

    world.clock.advance(119)
    result = world.accept(diff.hash())

    assert isinstance(result, PreparationAccepted)
    assert len(merchant.refresh_calls) == calls_after_prepare, "no second refresh"
    assert result.quote.total == Money.paise(60_500)


def test_the_quote_verifies_against_its_own_hash_and_is_stored() -> None:
    world = World()
    _prep, diff = world.prepare_ok(merchant_selling(59_500))
    result = world.accept_ok(diff.hash())
    assert result.quote.verify(result.quote.quote_hash) is None
    assert world.store.get(quote_key(PURCHASE_ID, result.quote.quote_id)) is not None


def test_an_unknown_fee_blocks_the_quote_and_names_the_charge() -> None:
    world = World()
    _prep, diff = world.prepare_ok(
        merchant_selling(59_500, fees=(Charge.unknown_charge(ChargeKind.DELIVERY),))
    )
    result = world.accept(diff.hash())
    assert isinstance(result, QuoteNotConstructible)
    assert result.reason == "unknown_charge"


def test_an_estimated_fee_yields_a_quote_priced_at_its_ceiling() -> None:
    """An estimated fee is approvable as a maximum (WP-02-A1).

    Pre-A1 this refused the quote. Because the live merchants can never report a
    complete fee, that refusal blocked every live purchase rather than
    protecting anyone -- so the quote is built and the control says "up to".
    """
    world = World()
    _prep, diff = world.prepare_ok(
        merchant_selling(
            59_500,
            fees=(Charge.known_charge(ChargeKind.SURGE, Money.paise(500), Confidence.ESTIMATED),),
        )
    )
    result = world.accept(diff.hash())
    # Narrow on DomainError, not just QuoteNotConstructible: the latter leaves
    # every other error in the union and .quote stays unreachable.
    assert not isinstance(result, DomainError), f"accept failed: {result}"
    quote = result.quote
    assert quote.total.amount_paise == 60_000
    assert quote.total_confidence is Confidence.ESTIMATED


def test_an_unpriced_line_blocks_the_quote_with_its_own_reason() -> None:
    world = World()
    _prep, diff = world.prepare_ok(
        ScriptedMerchant(
            observations={
                "rice-b": IncompatibleUnits(from_dimension="mass", to_dimension="volume")
            },
            fees=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
        )
    )
    result = world.accept(diff.hash())
    assert isinstance(result, QuoteNotConstructible)
    assert result.reason == "unpriced_line"


@pytest.mark.parametrize("elapsed", [120, 121, 300])
def test_a_stale_preparation_cannot_be_accepted(elapsed: int) -> None:
    world = World()
    _prep, diff = world.prepare_ok(merchant_selling(59_500))
    world.clock.advance(elapsed)
    assert isinstance(world.accept(diff.hash()), PreparationExpired)


def test_a_quote_carries_the_demo_seller_never_the_real_merchant() -> None:
    """Nothing here places an order with a real shop, so nothing names one."""
    world = World()
    _prep, diff = world.prepare_ok(merchant_selling(59_500))
    quote = world.accept_ok(diff.hash()).quote
    assert quote.demo_seller_id == "demo-seller-01"
    assert quote.source_merchant_id == "merchant-b"


def test_a_fixture_basket_produces_a_fixture_quote() -> None:
    """Mode rides through preparation into the quote hash."""
    world = World()
    basket = a_basket()
    fixture = basket.model_copy(update={"mode": Mode.FIXTURE})
    _prep, diff = world.prepare_ok(merchant_selling(59_500), basket=fixture)
    quote = world.accept_ok(diff.hash()).quote
    assert quote.mode is Mode.FIXTURE


# -- the whole journey, nothing stubbed ------------------------------------


def test_prepare_then_accept_then_approve_yields_one_attempt() -> None:
    world = World()
    _prep, diff = world.prepare_ok(merchant_selling(59_500))
    accepted = world.accept(diff.hash())
    assert isinstance(accepted, PreparationAccepted)

    approved = world.uc.approve(
        owner_id=OWNER,
        purchase_id=PURCHASE_ID,
        quote_id=accepted.quote.quote_id,
        quote_hash=accepted.quote.quote_hash,
        quote_version=accepted.quote.quote_version,
        expected_purchase_version=world.current_version(),
        idempotency="idem-journey",
    )
    assert isinstance(approved, AttemptCreated)
    assert world.store.count_matching("PROVIDER#") == 1


# -- the pure helpers, directly --------------------------------------------


def test_diff_between_is_pure_and_order_independent() -> None:
    world = World()
    world.prepare(merchant_selling(59_500))
    facts = world.facts()
    assert diff_between(a_basket(), facts).hash() == diff_between(a_basket(), facts).hash()


def test_build_quote_refuses_before_it_builds_anything() -> None:
    from services.domain.purchase import Preparation

    world = World()
    world.prepare(merchant_selling(59_500, fees=(Charge.unknown_charge(ChargeKind.DELIVERY),)))
    stale = Preparation(
        preparation_id="prep-0001",
        purchase_id=PURCHASE_ID,
        refreshed_at=NOW,
        diff_hash="d" * 64,
        change_count=0,
    )
    result = build_quote(
        purchase=world.purchase,
        preparation=stale,
        facts=world.facts(),
        quote_id="quote-00000001",
        quote_version=1,
        now=NOW,
    )
    assert isinstance(result, QuoteNotConstructible)
