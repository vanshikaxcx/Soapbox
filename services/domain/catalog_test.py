"""Matching, substitution and pack selection (WP-02 criteria 6, and units via packs)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from services.domain.catalog import (
    OVERBUY_LIMIT_BP,
    ExtractionStatus,
    Observation,
    PackOption,
    PackSelection,
    SubstitutionKind,
    check_substitution,
    is_usable,
    satisfies_hard_attributes,
    select_packs,
)
from services.domain.errors import (
    HardAttributeUnsatisfied,
    IncompatibleUnits,
    OverbuyLimitExceeded,
    SubstitutionNotPermitted,
)
from services.domain.ids import Mode
from services.domain.intent import Flexibility, Item
from services.domain.money import Money
from services.domain.units import Quantity, Unit

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def an_item(
    *,
    attributes: dict[str, str] | None = None,
    flexibility: Flexibility = Flexibility.EXACT_ONLY,
    quantity: Quantity | None = None,
) -> Item:
    return Item(
        item_id="item-0001",
        name="Basmati rice",
        quantity=quantity or Quantity.of(5, Unit.KG),
        hard_attributes=attributes or {},
        flexibility=flexibility,
    )


def an_observation(
    *,
    attributes: dict[str, str] | None = None,
    brand: str | None = None,
    in_stock: bool = True,
    status: ExtractionStatus = ExtractionStatus.OK,
) -> Observation:
    return Observation(
        observation_id="obs-00001",
        merchant_id="merchant-a",
        sku="sku-00001",
        url="https://merchant.example/p/1",
        name="Basmati rice 1kg",
        brand=brand,
        attributes=attributes or {},
        pack=Quantity.of(1, Unit.KG),
        price=Money.paise(12_000),
        in_stock=in_stock,
        verified_location="Indiranagar, Bengaluru",
        fetched_at=NOW,
        extraction_status=status,
        mode=Mode.LIVE,
    )


# -- hard attributes: absence is never assent ------------------------------


def test_a_matching_attribute_satisfies() -> None:
    item = an_item(attributes={"variety": "basmati"})
    observation = an_observation(attributes={"variety": "basmati"})
    assert satisfies_hard_attributes(item, observation) is None


def test_a_missing_attribute_never_satisfies() -> None:
    """"We don't know whether this is basmati" is not "yes"."""
    item = an_item(attributes={"variety": "basmati"})
    result = satisfies_hard_attributes(item, an_observation(attributes={}))
    assert isinstance(result, HardAttributeUnsatisfied)
    assert result.attribute == "variety"
    assert result.observed is None


def test_an_empty_attribute_value_never_satisfies() -> None:
    item = an_item(attributes={"variety": "basmati"})
    result = satisfies_hard_attributes(item, an_observation(attributes={"variety": ""}))
    assert isinstance(result, HardAttributeUnsatisfied)


def test_a_different_attribute_value_fails() -> None:
    item = an_item(attributes={"variety": "basmati"})
    result = satisfies_hard_attributes(item, an_observation(attributes={"variety": "sona"}))
    assert isinstance(result, HardAttributeUnsatisfied)
    assert result.observed == "sona"


def test_every_hard_attribute_must_be_satisfied_not_just_one() -> None:
    item = an_item(attributes={"variety": "basmati", "organic": "yes"})
    observation = an_observation(attributes={"variety": "basmati"})
    assert isinstance(satisfies_hard_attributes(item, observation), HardAttributeUnsatisfied)


def test_an_item_with_no_hard_attributes_is_satisfied_by_anything() -> None:
    assert satisfies_hard_attributes(an_item(), an_observation()) is None


# -- substitutions ---------------------------------------------------------


def test_a_brand_change_is_refused_without_flexibility() -> None:
    item = an_item(attributes={"brand": "India Gate"}, flexibility=Flexibility.EXACT_ONLY)
    result = check_substitution(item, an_observation(brand="Daawat"))
    assert isinstance(result, SubstitutionNotPermitted)
    assert result.kind == SubstitutionKind.BRAND.value


@pytest.mark.parametrize(
    "flexibility", [Flexibility.BRAND_FLEXIBLE, Flexibility.BRAND_AND_PACK_FLEXIBLE]
)
def test_a_brand_change_is_recorded_when_permitted(flexibility: Flexibility) -> None:
    item = an_item(attributes={"brand": "India Gate"}, flexibility=flexibility)
    result = check_substitution(item, an_observation(brand="Daawat"))
    assert result is not None and not isinstance(result, SubstitutionNotPermitted)
    assert result.requested == "India Gate"
    assert result.supplied == "Daawat"


def test_pack_flexibility_alone_does_not_permit_a_brand_change() -> None:
    item = an_item(attributes={"brand": "India Gate"}, flexibility=Flexibility.PACK_FLEXIBLE)
    assert isinstance(check_substitution(item, an_observation(brand="Daawat")),
                      SubstitutionNotPermitted)


def test_no_substitution_is_recorded_when_the_brand_matches() -> None:
    item = an_item(attributes={"brand": "India Gate"}, flexibility=Flexibility.BRAND_FLEXIBLE)
    assert check_substitution(item, an_observation(brand="India Gate")) is None


# -- pack selection --------------------------------------------------------


def option(sku: str, grams: int, paise: int) -> PackOption:
    return PackOption(sku=sku, pack=Quantity.of(grams, Unit.G), price=Money.paise(paise))


def test_an_exact_fit_has_no_overbuy() -> None:
    result = select_packs(Quantity.of(5, Unit.KG), [option("sku-a", 1000, 10_000)])
    assert isinstance(result, PackSelection)
    assert result.overbuy_base_units == 0
    assert result.pack_count == 5
    assert result.total_price == Money.paise(50_000)


def test_selection_minimises_overbuy_before_cost() -> None:
    # 2.5 kg needed. A 3 kg pack overbuys 500 g; five 500 g packs fit exactly
    # even though they cost slightly more.
    result = select_packs(
        Quantity.of(2500, Unit.G),
        [option("sku-big", 3000, 20_000), option("sku-small", 500, 4_200)],
    )
    assert isinstance(result, PackSelection)
    assert result.overbuy_base_units == 0
    assert result.counts == (("sku-small", 5),)


def test_among_exact_fits_the_cheaper_one_wins() -> None:
    result = select_packs(
        Quantity.of(1000, Unit.G),
        [option("sku-cheap", 1000, 9_000), option("sku-dear", 1000, 11_000)],
    )
    assert isinstance(result, PackSelection)
    assert result.counts == (("sku-cheap", 1),)


def test_selection_is_deterministic_under_input_reordering() -> None:
    options = [
        option("sku-a", 500, 5_000),
        option("sku-b", 1000, 9_500),
        option("sku-c", 250, 2_600),
    ]
    forward = select_packs(Quantity.of(2000, Unit.G), options)
    backward = select_packs(Quantity.of(2000, Unit.G), list(reversed(options)))
    assert isinstance(forward, PackSelection)
    assert forward == backward


def test_a_small_overbuy_within_the_limit_is_allowed_and_reported() -> None:
    # 900 g needed, only 1 kg packs: 100 g overbuy, well inside 1.5x.
    result = select_packs(Quantity.of(900, Unit.G), [option("sku-a", 1000, 10_000)])
    assert isinstance(result, PackSelection)
    assert result.overbuy_base_units == 100


def test_an_overbuy_beyond_the_limit_is_refused() -> None:
    # 100 g needed, only 1 kg packs: 10x. Far beyond 1.5x.
    result = select_packs(Quantity.of(100, Unit.G), [option("sku-a", 1000, 10_000)])
    assert isinstance(result, OverbuyLimitExceeded)
    assert result.limit_bp == OVERBUY_LIMIT_BP


@pytest.mark.parametrize(
    ("required", "pack", "allowed"),
    [
        (1000, 1500, True),   # exactly 1.5x
        (1000, 1501, False),  # just over
        (1000, 1499, True),   # just under
    ],
)
def test_the_overbuy_boundary_is_exactly_one_and_a_half(
    required: int, pack: int, allowed: bool
) -> None:
    result = select_packs(Quantity.of(required, Unit.G), [option("sku-a", pack, 10_000)])
    assert isinstance(result, PackSelection) is allowed


def test_a_pack_in_another_dimension_is_refused() -> None:
    result = select_packs(
        Quantity.of(1, Unit.KG),
        [PackOption(sku="sku-a", pack=Quantity.of(1, Unit.L), price=Money.paise(10_000))],
    )
    assert isinstance(result, IncompatibleUnits)


def test_no_options_means_no_selection() -> None:
    assert isinstance(select_packs(Quantity.of(1, Unit.KG), []), OverbuyLimitExceeded)


@given(
    st.integers(min_value=100, max_value=5_000),
    st.integers(min_value=100, max_value=2_000),
)
def test_a_selection_always_meets_the_requirement_and_respects_the_limit(
    required: int, pack: int
) -> None:
    result = select_packs(Quantity.of(required, Unit.G), [option("sku-a", pack, 1_000)])
    if isinstance(result, PackSelection):
        assert result.total_quantity.value_base >= required
        assert result.total_quantity.value_base * 10_000 <= required * OVERBUY_LIMIT_BP


# -- usability -------------------------------------------------------------


def test_an_out_of_stock_observation_is_not_usable() -> None:
    assert is_usable(an_observation(in_stock=False)) is False


@pytest.mark.parametrize("status", [ExtractionStatus.FAILED, ExtractionStatus.BLOCKED])
def test_an_unreadable_observation_is_not_usable(status: ExtractionStatus) -> None:
    assert is_usable(an_observation(status=status)) is False


def test_a_partially_extracted_but_stocked_observation_is_usable() -> None:
    assert is_usable(an_observation(status=ExtractionStatus.PARTIAL)) is True
