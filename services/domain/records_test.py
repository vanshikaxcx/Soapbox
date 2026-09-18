"""Cross-cutting record conventions (WP-02 acceptance criteria 15, 16).

Frozen records, aware-UTC timestamps, constrained IDs, and a UsualBasket that is
structurally incapable of holding commerce state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from services.domain.conversation import Conversation, Question, QuestionKind
from services.domain.evidence import Case, Evidence, EvidenceKind, InboxEvent
from services.domain.ids import Mode, Record, is_valid_id
from services.domain.intent import Intent, Item, Preferences, UsualBasket
from services.domain.jobs import Job, OutboxEvent
from services.domain.money import Money
from services.domain.units import Quantity, Unit

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

ALL_RECORDS = [
    Conversation,
    Question,
    Case,
    Evidence,
    InboxEvent,
    Intent,
    Item,
    Job,
    OutboxEvent,
    Preferences,
    UsualBasket,
]


def an_item(item_id: str = "item-0001") -> Item:
    return Item(item_id=item_id, name="Basmati rice", quantity=Quantity.of(5, Unit.KG))


def an_intent() -> Intent:
    return Intent(
        intent_id="intent-0001",
        owner_id="owner-0001",
        items=(an_item(),),
        location="Indiranagar, Bengaluru",
        budget_paise=90_000,
    )


# -- frozen ----------------------------------------------------------------


@pytest.mark.parametrize("model", ALL_RECORDS, ids=lambda m: m.__name__)
def test_every_record_is_frozen(model: type[BaseModel]) -> None:
    assert model.model_config.get("frozen") is True


def test_assignment_to_a_record_raises() -> None:
    intent = an_intent()
    with pytest.raises(ValidationError):
        intent.revision = 5  # type: ignore[misc]


def test_a_mutation_returns_a_new_record_leaving_the_original_alone() -> None:
    from services.domain.intent import revise

    original = an_intent()
    updated = revise(original, (an_item("item-0002"),))
    assert original.revision == 1
    assert updated.revision == 2
    assert original.items[0].item_id == "item-0001"


# -- strict and closed -----------------------------------------------------


@pytest.mark.parametrize("model", ALL_RECORDS, ids=lambda m: m.__name__)
def test_every_record_is_strict_and_forbids_extra_fields(model: type[BaseModel]) -> None:
    assert model.model_config.get("strict") is True
    assert model.model_config.get("extra") == "forbid"


def test_an_unexpected_field_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ValidationError):
        Item(
            item_id="item-0001",
            name="Rice",
            quantity=Quantity.of(1, Unit.KG),
            price_paise=1000,  # type: ignore[call-arg]
        )


# -- timestamps ------------------------------------------------------------


def _evidence(observed_at: datetime) -> Evidence:
    return Evidence(
        evidence_id="evidence-01",
        purchase_id="purchase-01",
        kind=EvidenceKind.APPROVAL,
        source_ref="ref",
        observed_at=observed_at,
    )


def test_a_naive_timestamp_is_rejected_at_construction() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _evidence(datetime(2026, 9, 15, 12, 0, 0))


def test_an_aware_timestamp_is_normalised_to_utc() -> None:
    from datetime import timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    evidence = _evidence(datetime(2026, 9, 15, 17, 30, 0, tzinfo=ist))
    assert evidence.observed_at == NOW
    assert evidence.observed_at.tzinfo is UTC


def test_a_string_is_not_accepted_where_an_enum_is_declared() -> None:
    """Strict mode means no coercion, including for enums."""
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="evidence-01",
            purchase_id="purchase-01",
            kind="approval",  # type: ignore[arg-type]
            source_ref="ref",
            observed_at=NOW,
        )


# -- identifiers -----------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["short", "has space", "has/slash", "has\nnewline", "", "x" * 65, "tab\there"],
)
def test_malformed_ids_are_rejected(bad: str) -> None:
    assert not is_valid_id(bad)
    with pytest.raises(ValidationError):
        Conversation(conversation_id=bad, owner_id="owner-0001")


@pytest.mark.parametrize("good", ["abcdefgh", "owner-0001", "a_b-c123", "x" * 64])
def test_well_formed_ids_are_accepted(good: str) -> None:
    assert is_valid_id(good)


def test_an_id_cannot_carry_a_separator_into_a_signing_input() -> None:
    """The reason the charset is constrained at all."""
    assert not is_valid_id("owner\n0001")
    assert not is_valid_id("owner:0001")


# -- the usual basket holds no commerce state ------------------------------

FORBIDDEN_FIELD_HINTS = (
    "price",
    "paise",
    "amount",
    "total",
    "quote",
    "approval",
    "payment",
    "attempt",
    "provider",
    "charge",
    "fee",
)


def test_usual_basket_has_no_field_that_could_hold_a_price_or_payment_identity() -> None:
    for name in UsualBasket.model_fields:
        assert not any(hint in name.lower() for hint in FORBIDDEN_FIELD_HINTS), (
            f"UsualBasket.{name} looks like commerce state"
        )
    for name in Preferences.model_fields:
        assert not any(hint in name.lower() for hint in FORBIDDEN_FIELD_HINTS)


def _mentions_money(annotation: object) -> bool:
    if annotation is Money:
        return True
    origin = get_origin(annotation)
    if origin is not None:
        return any(_mentions_money(arg) for arg in get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return any(_mentions_money(field.annotation) for field in annotation.model_fields.values())
    return False


def test_no_field_reachable_from_a_usual_basket_is_money_typed() -> None:
    """Structural, not nominal: a renamed price field would still be caught."""
    for field in UsualBasket.model_fields.values():
        assert not _mentions_money(field.annotation)


def test_an_intent_may_carry_a_budget_but_a_usual_basket_may_not() -> None:
    assert "budget_paise" in Intent.model_fields
    assert "budget_paise" not in UsualBasket.model_fields


# -- limits ----------------------------------------------------------------


def test_an_intent_is_capped_at_four_items() -> None:
    items = tuple(an_item(f"item-000{n}") for n in range(1, 6))
    with pytest.raises(ValidationError):
        Intent(
            intent_id="intent-0001",
            owner_id="owner-0001",
            items=items,
            location="Indiranagar, Bengaluru",
        )


def test_duplicate_item_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Intent(
            intent_id="intent-0001",
            owner_id="owner-0001",
            items=(an_item("item-0001"), an_item("item-0001")),
            location="Indiranagar, Bengaluru",
        )


# -- questions never approve ----------------------------------------------


def test_no_question_kind_mutates_a_purchase() -> None:
    """WP-08 relies on this: a conversation answer cannot become an approval."""
    from services.domain.conversation import PURCHASE_MUTATING_QUESTION_KINDS

    assert frozenset() == PURCHASE_MUTATING_QUESTION_KINDS
    for kind in QuestionKind:
        assert "approve" not in kind.value
        assert "pay" not in kind.value


# -- mode ------------------------------------------------------------------


def test_mode_has_exactly_two_values() -> None:
    assert set(Mode) == {Mode.LIVE, Mode.FIXTURE}


def test_the_record_base_is_what_every_record_inherits() -> None:
    for model in ALL_RECORDS:
        assert issubclass(model, Record)
