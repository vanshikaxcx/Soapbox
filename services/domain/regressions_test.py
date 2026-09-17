"""Regressions from the WP-02 implementation review.

Each test here would have failed before its fix. They live together so the
review's findings stay visible rather than dissolving into the suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from services.domain.basket import (
    BasketCost,
    Comparison,
    cheaper_of,
    cheapest,
    compare_baskets,
)
from services.domain.ids import Mode
from services.domain.intent import Item
from services.domain.money import Amount, Money, compute_totals
from services.domain.provider import (
    Applied,
    Current,
    OrderFacts,
    PaymentFacts,
    apply_order_facts,
    apply_payment_facts,
)
from services.domain.transitions import (
    ClaimEvent,
    ClaimState,
    DispatchState,
    OrderEvent,
    OrderState,
    PaymentEvent,
    PaymentState,
    RefundState,
    StateMachineMisuse,
    apply,
    is_terminal,
)
from services.domain.units import Quantity, Unit

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
LATER = NOW + timedelta(seconds=60)


# -- R1: cross-machine state confusion (critical) --------------------------
#
# StrEnum members compare and hash equal to any string of the same value, so
# OrderState.PENDING == PaymentState.PENDING. Table lookups therefore matched
# across machines and an order state fed to the payment machine silently
# transitioned into a payment state.


def test_strenum_members_really_do_collide_across_machines() -> None:
    """The premise. If this ever stops being true, the guard can be relaxed."""
    # mypy calls this non-overlapping because the enums are nominally distinct.
    # They are StrEnums, so at runtime both are "pending" and they do compare
    # equal -- which is the hazard this test exists to document.
    assert OrderState.PENDING == PaymentState.PENDING  # type: ignore[comparison-overlap]
    assert hash(OrderState.PENDING) == hash(PaymentState.PENDING)


def test_a_state_from_another_machine_is_refused() -> None:
    with pytest.raises(StateMachineMisuse, match="expected a PaymentState"):
        apply("payment", OrderState.PENDING, PaymentEvent.REPORT_SUCCEEDED)


def test_an_event_from_another_machine_is_refused() -> None:
    with pytest.raises(StateMachineMisuse, match="expected a PaymentEvent"):
        apply("payment", PaymentState.PENDING, OrderEvent.REPORT_CONFIRMED)


def test_a_bare_string_is_refused_even_though_it_compares_equal() -> None:
    with pytest.raises(StateMachineMisuse):
        apply("payment", "pending", PaymentEvent.REPORT_SUCCEEDED)  # type: ignore[arg-type]


def test_is_terminal_refuses_a_foreign_state_too() -> None:
    """It used to answer True for RefundState.FAILED on the payment machine."""
    with pytest.raises(StateMachineMisuse):
        is_terminal("payment", RefundState.FAILED)


def test_fact_application_refuses_a_mismatched_current_state() -> None:
    """Current.state is a union of three state types, which is how this was
    reachable from the real callback path rather than only in theory."""
    mismatched = Current(state=OrderState.PENDING, observed_at=NOW)
    with pytest.raises(StateMachineMisuse):
        apply_payment_facts(
            mismatched, PaymentFacts(state=PaymentState.SUCCEEDED, observed_at=LATER)
        )


def test_matching_machines_still_work_normally() -> None:
    assert apply("payment", PaymentState.PENDING, PaymentEvent.REPORT_SUCCEEDED) is (
        PaymentState.SUCCEEDED
    )
    assert apply("claim", ClaimState.RELEASED, ClaimEvent.CLAIM) is ClaimState.CLAIMED
    assert is_terminal("dispatch", DispatchState.STARTED) is True


# -- R2: naive datetimes in provider records (critical) --------------------
#
# Current and Applied extended Record, not Timestamped, so a naive datetime
# passed validation and then raised a bare TypeError inside fact application --
# in the callback ingestion path.


def test_a_naive_observation_time_is_rejected_at_construction() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Current(state=PaymentState.PENDING, observed_at=datetime(2026, 9, 15, 12, 0, 0))


def test_applied_also_refuses_a_naive_time() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Applied(
            state=PaymentState.PENDING,
            observed_at=datetime(2026, 9, 15, 12, 0, 0),
            changed=True,
        )


def test_fact_application_no_longer_raises_a_bare_type_error() -> None:
    """Previously: TypeError('can't compare offset-naive and offset-aware')."""
    current = Current(state=PaymentState.PENDING, observed_at=NOW)
    result = apply_payment_facts(
        current, PaymentFacts(state=PaymentState.SUCCEEDED, observed_at=LATER)
    )
    assert isinstance(result, Applied)


def test_an_offset_aware_time_is_normalised_so_comparisons_are_safe() -> None:
    from datetime import timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    current = Current(state=OrderState.PENDING, observed_at=datetime(
        2026, 9, 15, 17, 30, 0, tzinfo=ist
    ))
    assert current.observed_at == NOW
    result = apply_order_facts(
        current, OrderFacts(state=OrderState.CONFIRMED, observed_at=LATER)
    )
    assert isinstance(result, Applied)


# -- R3: an unpriced line reported as a phantom fee ------------------------


def test_an_unpriced_line_is_not_reported_as_an_unknown_other_charge() -> None:
    """It used to come back as unknown_charges=(OTHER,), so the UI would say we
    could not confirm a fee when the truth is we could not price an item."""
    totals = compute_totals([Amount.known(Money.paise(10_000)), Amount.unknown()], [])
    assert totals.unknown_charges == ()
    assert totals.unpriced_lines == 1


# -- R4: the dedicated DiffNotAccepted was declared but never returned -----


def test_an_unaccepted_diff_returns_its_own_error() -> None:
    from services.domain.errors import DiffNotAccepted
    from services.domain.purchase import Preparation, can_build_quote

    prep = Preparation(
        preparation_id="prep-0001",
        purchase_id="purchase-001",
        refreshed_at=NOW,
        diff_hash="d" * 64,
        change_count=2,
    )
    totals = compute_totals([Amount.known(Money.paise(1_000))], [])
    assert isinstance(can_build_quote(prep, totals, NOW), DiffNotAccepted)


# -- R5: cheapest() dropped duplicates by identity -------------------------


def _verified(paise: int, basket_id: str) -> BasketCost:
    return BasketCost(
        basket_id=basket_id,
        mode=Mode.LIVE,
        totals=compute_totals([Amount.known(Money.paise(paise))], []),
    )


def test_the_same_basket_listed_twice_is_not_declared_cheapest() -> None:
    """Identity exclusion removed both entries, leaving it to 'beat' nothing."""
    duplicated = _verified(9_000, "a")
    assert cheapest([duplicated, duplicated]) is None


def test_two_equal_but_distinct_baskets_are_still_a_tie() -> None:
    verdict = compare_baskets(_verified(9_000, "a"), _verified(9_000, "b"))
    assert isinstance(verdict, Comparison) and verdict.value == "equal"
    assert cheapest([_verified(9_000, "a"), _verified(9_000, "b")]) is None


# -- R6: a zero-quantity requirement was a free, empty basket --------------


def test_an_item_you_want_none_of_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Item(item_id="item-0001", name="Rice", quantity=Quantity.of(0, Unit.KG))


def test_pack_selection_refuses_a_non_positive_requirement() -> None:
    """It used to return an empty selection costing zero paise."""
    from services.domain.catalog import PackOption, select_packs

    with pytest.raises(ValueError, match="non-positive"):
        select_packs(
            Quantity.of(0, Unit.G),
            [PackOption(sku="s", pack=Quantity.of(1000, Unit.G), price=Money.paise(100))],
        )


# -- R7: hash-shaped fields typed as bare strings --------------------------


def test_preparation_hashes_must_look_like_digests() -> None:
    from services.domain.purchase import Preparation

    with pytest.raises(ValidationError):
        Preparation(
            preparation_id="prep-0001",
            purchase_id="purchase-001",
            refreshed_at=NOW,
            diff_hash="not-a-digest",
            change_count=0,
        )


def test_a_voice_transcript_hash_must_look_like_a_digest() -> None:
    from services.domain.conversation import VoiceSession

    with pytest.raises(ValidationError):
        VoiceSession(
            voice_session_id="voice-0001",
            owner_id="owner-0001",
            conversation_id="conversation-01",
            conversation_version=1,
            expires_at=LATER,
            submitted_transcript_hash="nope",
        )


# -- R8: the comparator's result could be read as the opposite of the truth --
#
# Found by a human clicking through the playground, not by any test.
# Comparison.A_CHEAPER meant "the first argument is cheaper", but the demo
# compares merchant B against merchant A -- so a result where B genuinely won
# came back as "a_cheaper", which reads as "merchant A is cheaper".


def test_the_enum_no_longer_borrows_names_from_the_things_being_compared() -> None:
    from services.domain.basket import Comparison

    names = {member.name for member in Comparison}
    assert "A_CHEAPER" not in names and "B_CHEAPER" not in names
    assert {"LEFT_CHEAPER", "RIGHT_CHEAPER"} <= names


def test_the_positional_meaning_is_what_it_says() -> None:
    cheap = _verified(59_000, "merchant-b")
    dear = _verified(62_000, "merchant-a")
    from services.domain.basket import Comparison, compare_baskets

    assert compare_baskets(cheap, dear) is Comparison.LEFT_CHEAPER
    assert compare_baskets(dear, cheap) is Comparison.RIGHT_CHEAPER


def test_cheaper_of_returns_the_winner_so_position_cannot_be_misread() -> None:
    """The exact case that confused a reader: B at Rs 590 vs A at Rs 620."""

    merchant_b = _verified(59_000, "merchant-b")
    merchant_a = _verified(62_000, "merchant-a")

    # Whichever order they are passed in, the winner is the same object.
    for left, right in ((merchant_b, merchant_a), (merchant_a, merchant_b)):
        winner = cheaper_of(left, right)
        assert isinstance(winner, BasketCost)
        assert winner.basket_id == "merchant-b"


def test_cheaper_of_returns_none_when_nothing_can_be_proven() -> None:
    from services.domain.basket import cheaper_of
    from services.domain.money import Charge, ChargeKind, compute_totals

    unknown_fee = BasketCost(
        basket_id="merchant-b",
        mode=Mode.LIVE,
        totals=compute_totals(
            [Amount.known(Money.paise(58_000))],
            [Charge.unknown_charge(ChargeKind.DELIVERY)],
        ),
    )
    assert cheaper_of(unknown_fee, _verified(62_000, "merchant-a")) is None
