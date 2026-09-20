"""Regressions from the WP-08 implementation review.

Each of these failed before its fix. The pack-size one is the sharpest: it put a
wrong number on the approval card, which is the single failure this whole project
argues against.
"""

from __future__ import annotations

from services.application.fakes import ScriptedMerchant
from services.application.ports import read
from services.application.prepare import RefreshedFacts, build_quote
from services.application.prepare_test import (
    LOCATION,
    NOW,
    PURCHASE_ID,
    World,
    an_observation,
    merchant_selling,
)
from services.application.purchase import preparation_key
from services.domain.errors import QuoteNotConstructible
from services.domain.money import Charge, ChargeKind, Money
from services.domain.purchase import Preparation
from services.domain.units import Quantity, Unit

# -- R1: a re-check was impossible -----------------------------------------
#
# prepare() always wrote version 1, so the second call died on its own
# must-not-exist guard. The spec's own screen matrix has a Re-check button for a
# stale preparation, so this made a documented flow unreachable.


def test_a_purchase_can_be_prepared_more_than_once() -> None:
    world = World()
    first, _ = world.prepare_ok(merchant_selling(59_500))
    second, _ = world.prepare_ok(merchant_selling(61_000))
    assert first.version == 1
    assert second.version == 2


def test_the_shopper_can_recheck_after_a_preparation_goes_stale() -> None:
    """The flow the UI state matrix promises, end to end."""
    world = World()
    _first, _diff = world.prepare_ok(merchant_selling(59_500))
    world.clock.advance(121)

    second, diff = world.prepare_ok(merchant_selling(61_000))
    assert second.version == 2

    accepted = world.accept_ok(diff.hash(), version=2)
    assert accepted.quote.total == Money.paise(62_000)


def test_each_preparation_keeps_its_own_facts() -> None:
    world = World()
    world.prepare(merchant_selling(59_500))
    world.prepare(merchant_selling(61_000))

    first: RefreshedFacts = world.facts(1)
    second: RefreshedFacts = world.facts(2)
    assert first.lines[0].line_total.amount == Money.paise(59_500)
    assert second.lines[0].line_total.amount == Money.paise(61_000)


def test_the_quote_version_follows_the_preparation_it_came_from() -> None:
    world = World()
    world.prepare(merchant_selling(59_500))
    _prep, diff = world.prepare_ok(merchant_selling(61_000))
    accepted = world.accept_ok(diff.hash(), version=2)
    assert accepted.quote.quote_version == 2


def test_two_concurrent_recheckings_cannot_land_on_one_version() -> None:
    """The counter advances under a conditional write, so one of them loses."""
    world = World()
    others = []

    def racer(_writes: object) -> None:
        others.append(world.prepare(merchant_selling(60_000)))

    world.memory.before_transact = racer
    world.prepare(merchant_selling(59_500))

    versions = [read(world.store, preparation_key(PURCHASE_ID, v), Preparation) for v in (1, 2, 3)]
    written = [p for p in versions if p is not None]
    assert len({p.version for p in written}) == len(written), "no version reused"


# -- R2: a pack-size change was silently mis-priced ------------------------


def _merchant_with_pack(pack_kg: int, paise: int) -> ScriptedMerchant:
    observation = an_observation("rice-b", paise).model_copy(
        update={"pack": Quantity.of(pack_kg, Unit.KG)}
    )
    return ScriptedMerchant(
        observations={"rice-b": observation},
        fees=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
    )


def test_a_shrunken_pack_is_never_priced_as_the_old_one() -> None:
    """Basket held one 5 kg pack. The merchant now lists a 1 kg pack.

    The old code multiplied the stored pack count (1) by the new pack's price,
    quoting five kilos of rice at the cost of one.
    """
    world = World()
    world.prepare(_merchant_with_pack(1, 12_000))
    line = world.facts().lines[0]
    assert line.line_total.amount is None, "a changed pack must not be re-priced here"
    assert line.pack_changed is True
    assert line.failure_code == "pack_size_changed"


def test_a_pack_change_says_what_the_pack_changed_to() -> None:
    """Writing this test caught the fix showing 5000 -> 5000, which says nothing."""
    world = World()
    _prep, diff = world.prepare_ok(_merchant_with_pack(1, 12_000))
    packs = [c for c in diff.changes if c.kind.value == "pack"]
    assert len(packs) == 1
    assert (packs[0].before, packs[0].after) == ("5000", "1000")


def test_a_changed_pack_blocks_the_quote_rather_than_guessing() -> None:
    world = World()
    _prep, diff = world.prepare_ok(_merchant_with_pack(1, 12_000))
    result = world.accept(diff.hash())
    assert isinstance(result, QuoteNotConstructible)
    assert result.reason == "unpriced_line"


def test_an_unchanged_pack_still_prices_normally() -> None:
    """The fix must not make every refresh refuse."""
    world = World()
    world.prepare(_merchant_with_pack(5, 59_500))
    assert world.facts().lines[0].line_total.amount == Money.paise(59_500)


def test_the_pack_count_comes_from_the_quantity_not_a_stored_tally() -> None:
    """A basket needing 2 packs of 2.5 kg prices as two packs, not one."""
    from services.domain.basket import BasketLine, FeeAssessment, build_basket
    from services.domain.ids import Mode
    from services.domain.money import Amount

    line = BasketLine(
        item_id="item-0001",
        observation_id="obs-00001",
        merchant_id="merchant-b",
        sku="rice-b",
        name="Basmati rice",
        pack_counts=(("rice-b", 2),),
        selected_base_units=5000,
        pack_base_units=2500,
        dimension="mass",
        unit_price=Money.paise(30_000),
        line_total=Amount.known(Money.paise(60_000)),
    )
    basket = build_basket(
        basket_id="basket-0001",
        search_id="search-0001",
        merchant_id="merchant-b",
        mode=Mode.LIVE,
        lines=(line,),
        fee_assessment=FeeAssessment(
            merchant_id="merchant-b",
            location=LOCATION,
            line_hash="a" * 64,
            subtotal=Money.paise(60_000),
            assessed_at=NOW,
            charges=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
        ),
    )
    merchant = ScriptedMerchant(
        observations={
            "rice-b": an_observation("rice-b", 30_000).model_copy(
                update={"pack": Quantity.of(2500, Unit.G)}
            )
        },
        fees=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
    )
    world = World()
    world.prepare(merchant, basket=basket)
    assert world.facts().lines[0].line_total.amount == Money.paise(60_000)


# -- R3: build_quote relied on another rule to keep None out ----------------


def test_build_quote_refuses_an_unpriced_line_on_its_own() -> None:
    """Asserted directly rather than trusting can_build_quote to get there first."""
    world = World()
    world.prepare(
        ScriptedMerchant(
            observations={"rice-b": an_observation("rice-b", 59_500, in_stock=False)},
            fees=(Charge.known_charge(ChargeKind.DELIVERY, Money.paise(1_000)),),
        )
    )
    facts = world.facts()
    assert facts.lines[0].line_total.amount is None

    # A preparation that claims to be fresh and accepted, so can_build_quote
    # would not block on those grounds.
    accepted = Preparation(
        preparation_id="prep-0001",
        purchase_id=PURCHASE_ID,
        refreshed_at=NOW,
        diff_hash="d" * 64,
        change_count=0,
    )
    result = build_quote(
        purchase=world.purchase_row(),
        preparation=accepted,
        facts=facts,
        quote_id="quote-00000001",
        quote_version=1,
        now=NOW,
    )
    assert isinstance(result, QuoteNotConstructible)
