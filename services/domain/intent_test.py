"""Intent revisions versus versions (WP-02).

The distinction with consequences: a search binds to a *revision*, so an old
search can never become current again once a repair is accepted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.domain.intent import (
    Flexibility,
    Intent,
    Item,
    Preferences,
    UsualBasket,
    is_current_revision,
    revise,
    to_intent_items,
    touch,
)
from services.domain.units import Quantity, Unit


def an_item(item_id: str = "item-0001", name: str = "Basmati rice") -> Item:
    return Item(item_id=item_id, name=name, quantity=Quantity.of(5, Unit.KG))


def an_intent() -> Intent:
    return Intent(
        intent_id="intent-0001",
        owner_id="owner-0001",
        items=(an_item(),),
        location="Indiranagar, Bengaluru",
        budget_paise=90_000,
    )


# -- revision vs version ---------------------------------------------------


def test_accepting_a_content_change_advances_both_counters() -> None:
    updated = revise(an_intent(), (an_item("item-0002", "Sona masoori"),))
    assert updated.revision == 2
    assert updated.version == 2


def test_a_non_content_change_advances_only_the_version() -> None:
    """So an in-flight search stays current when nothing being bought changed."""
    updated = touch(an_intent())
    assert updated.revision == 1
    assert updated.version == 2


def test_a_search_on_an_older_revision_is_never_current_again() -> None:
    intent = an_intent()
    assert is_current_revision(intent, 1) is True

    after_repair = revise(intent, (an_item("item-0002"),))
    assert is_current_revision(after_repair, 1) is False
    assert is_current_revision(after_repair, 2) is True


def test_revisions_only_move_forward() -> None:
    intent = an_intent()
    for expected in (2, 3, 4):
        intent = revise(intent, (an_item(f"item-000{expected}"),))
        assert intent.revision == expected


# -- flexibility -----------------------------------------------------------


@pytest.mark.parametrize(
    ("flexibility", "brand", "pack"),
    [
        (Flexibility.EXACT_ONLY, False, False),
        (Flexibility.BRAND_FLEXIBLE, True, False),
        (Flexibility.PACK_FLEXIBLE, False, True),
        (Flexibility.BRAND_AND_PACK_FLEXIBLE, True, True),
    ],
)
def test_flexibility_permits_exactly_what_it_names(
    flexibility: Flexibility, brand: bool, pack: bool
) -> None:
    assert flexibility.allows_brand_change is brand
    assert flexibility.allows_pack_change is pack


def test_the_default_flexibility_is_the_strictest() -> None:
    assert an_item().flexibility is Flexibility.EXACT_ONLY


# -- validation ------------------------------------------------------------


def test_a_hard_attribute_needs_both_a_name_and_a_value() -> None:
    with pytest.raises(ValidationError):
        Item(
            item_id="item-0001",
            name="Rice",
            quantity=Quantity.of(1, Unit.KG),
            hard_attributes={"variety": ""},
        )


def test_an_intent_needs_at_least_one_item() -> None:
    with pytest.raises(ValidationError):
        Intent(
            intent_id="intent-0001",
            owner_id="owner-0001",
            items=(),
            location="Indiranagar, Bengaluru",
        )


def test_a_negative_budget_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Intent(
            intent_id="intent-0001",
            owner_id="owner-0001",
            items=(an_item(),),
            location="Indiranagar, Bengaluru",
            budget_paise=-1,
        )


def test_a_budget_is_optional_because_not_every_shopper_states_one() -> None:
    intent = Intent(
        intent_id="intent-0001",
        owner_id="owner-0001",
        items=(an_item(),),
        location="Indiranagar, Bengaluru",
    )
    assert intent.budget_paise is None


# -- usual basket ----------------------------------------------------------


def test_loading_a_usual_basket_carries_items_only() -> None:
    usual = UsualBasket(
        owner_id="owner-0001",
        items=(an_item(),),
        preferences=Preferences(location="Indiranagar, Bengaluru"),
    )
    items = to_intent_items(usual)
    assert items == usual.items
    assert all(isinstance(item, Item) for item in items)
