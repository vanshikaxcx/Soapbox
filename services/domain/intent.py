"""The shopping request, and the usual basket (WP-02).

``Intent`` is a shopping request. Its counter is ``revision`` and it increments
only on an accepted content change -- a user edit, or an accepted repair. Every
other record uses ``version`` for optimistic concurrency. Keeping the two words
apart matters: a search binds to an intent *revision*, so an old search can never
become current again after a repair is accepted.

``UsualBasket`` deliberately cannot hold a price, a quote, an approval or a
payment identity. Loading it starts a fresh search; it never replays an old one.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from services.domain.ids import Id, Record
from services.domain.units import Quantity

#: SPEC section 1: at most four distinct items.
MAX_ITEMS = 4


class Flexibility(StrEnum):
    """What the shopper will accept instead of exactly what they asked for."""

    EXACT_ONLY = "exact_only"
    BRAND_FLEXIBLE = "brand_flexible"
    PACK_FLEXIBLE = "pack_flexible"
    BRAND_AND_PACK_FLEXIBLE = "brand_and_pack_flexible"

    @property
    def allows_brand_change(self) -> bool:
        return self in (Flexibility.BRAND_FLEXIBLE, Flexibility.BRAND_AND_PACK_FLEXIBLE)

    @property
    def allows_pack_change(self) -> bool:
        return self in (Flexibility.PACK_FLEXIBLE, Flexibility.BRAND_AND_PACK_FLEXIBLE)


class DeliveryConstraint(StrEnum):
    ANY = "any"
    SAME_DAY = "same_day"
    SCHEDULED = "scheduled"


class Item(Record):
    """One line of a shopping request."""

    item_id: Id
    name: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    hard_attributes: dict[str, str] = Field(default_factory=dict)
    flexibility: Flexibility = Flexibility.EXACT_ONLY

    @field_validator("quantity")
    @classmethod
    def _quantity_is_positive(cls, value: Quantity) -> Quantity:
        if value.value_base <= 0:
            raise ValueError("an item you want none of is not an item")
        return value

    @field_validator("hard_attributes")
    @classmethod
    def _attributes_are_non_empty(cls, value: dict[str, str]) -> dict[str, str]:
        for key, attribute in value.items():
            if not key or not attribute:
                raise ValueError("a hard attribute needs both a name and a value")
        return value


class Intent(Record):
    """A shopping request at a particular revision."""

    intent_id: Id
    owner_id: Id
    items: tuple[Item, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    location: str = Field(min_length=1, max_length=200)
    budget_paise: int | None = Field(default=None, ge=0)
    delivery_constraint: DeliveryConstraint = DeliveryConstraint.ANY
    revision: int = Field(default=1, ge=1)
    version: int = Field(default=1, ge=1)

    @field_validator("items")
    @classmethod
    def _item_ids_are_distinct(cls, value: tuple[Item, ...]) -> tuple[Item, ...]:
        ids = [item.item_id for item in value]
        if len(set(ids)) != len(ids):
            raise ValueError("item ids must be distinct within an intent")
        return value


class Preferences(Record):
    """Standing preferences saved with a usual basket. No commerce state."""

    location: str | None = None
    delivery_constraint: DeliveryConstraint = DeliveryConstraint.ANY
    default_flexibility: Flexibility = Flexibility.EXACT_ONLY


class UsualBasket(Record):
    """A saved list plus preferences.

    There is no field here capable of holding a price, a quote, an approval or a
    payment identity, and a test asserts that structurally. Loading a usual
    basket triggers fresh observations; it never replays an old price.
    """

    owner_id: Id
    items: tuple[Item, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    preferences: Preferences = Preferences()
    version: int = Field(default=1, ge=1)


def revise(intent: Intent, items: tuple[Item, ...]) -> Intent:
    """Accept a content change: new items, revision and version both advance."""
    return intent.model_copy(
        update={
            "items": items,
            "revision": intent.revision + 1,
            "version": intent.version + 1,
        }
    )


def touch(intent: Intent) -> Intent:
    """A non-content change: version advances, revision does not.

    Used for edits that do not alter what is being bought, so an in-flight search
    stays current.
    """
    return intent.model_copy(update={"version": intent.version + 1})


def is_current_revision(intent: Intent, search_revision: int) -> bool:
    """A search bound to an older revision can never become current again."""
    return search_revision == intent.revision


def to_intent_items(usual: UsualBasket) -> tuple[Item, ...]:
    """Items only. Nothing else in a usual basket is allowed to travel."""
    return usual.items


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "DeliveryConstraint",
    "Flexibility",
    "Intent",
    "Item",
    "MAX_ITEMS",
    "Preferences",
    "UsualBasket",
    "is_current_revision",
    "revise",
    "to_intent_items",
    "touch",
]
