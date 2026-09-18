"""The commerce core records (WP-02 acceptance criteria 6, 7, 17).

These are what WP-08 writes in one transaction and WP-09 reads on every attempt.
The tests concentrate on the invariants that make a duplicate payment or a
mis-stated total impossible to represent at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from services.domain.basket import Basket, BasketLine, FeeAssessment, build_basket
from services.domain.catalog import Substitution, SubstitutionKind
from services.domain.ids import Mode
from services.domain.keys import approval_id, payment_key, quote_hash
from services.domain.money import (
    Amount,
    Charge,
    ChargeKind,
    Confidence,
    Currency,
    Money,
    compute_totals,
)
from services.domain.purchase import (
    Approval,
    Attempt,
    CheckoutQuote,
    Purchase,
    QuoteLine,
    build_attempt_and_lookup,
)
from services.domain.transitions import (
    ApprovalState,
    ClaimState,
    DispatchState,
    OrderState,
    PaymentState,
)

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(seconds=120)


# -- basket ----------------------------------------------------------------


def a_line(paise: int = 60_000, merchant: str = "merchant-a") -> BasketLine:
    return BasketLine(
        item_id="item-0001",
        observation_id="obs-00001",
        merchant_id=merchant,
        sku="sku-00001",
        name="Basmati rice 1kg",
        pack_counts=(("sku-00001", 5),),
        selected_base_units=5000,
        pack_base_units=1000,
        unit_price=Money.paise(12_000),
        line_total=Amount.known(Money.paise(paise)),
    )


def a_fee_assessment(*charges: Charge) -> FeeAssessment:
    return FeeAssessment(
        merchant_id="merchant-a",
        location="Indiranagar, Bengaluru",
        line_hash="a" * 64,
        subtotal=Money.paise(60_000),
        assessed_at=NOW,
        charges=charges,
    )


def test_a_basket_computes_its_own_totals() -> None:
    basket = build_basket(
        basket_id="basket-0001",
        search_id="search-0001",
        merchant_id="merchant-a",
        mode=Mode.LIVE,
        lines=(a_line(),),
        fee_assessment=a_fee_assessment(
            Charge.known_charge(ChargeKind.DELIVERY, Money.paise(2_000))
        ),
    )
    assert basket.totals.total == Money.paise(62_000)


def test_a_basket_whose_total_disagrees_with_its_lines_cannot_exist() -> None:
    """The single most damaging thing this system could display."""
    wrong = compute_totals([Amount.known(Money.paise(1))], [])
    with pytest.raises(ValidationError, match="totals do not match"):
        Basket(
            basket_id="basket-0001",
            search_id="search-0001",
            merchant_id="merchant-a",
            mode=Mode.LIVE,
            lines=(a_line(),),
            totals=wrong,
        )


def test_a_basket_is_single_merchant() -> None:
    with pytest.raises(ValidationError, match="basket's merchant"):
        build_basket(
            basket_id="basket-0001",
            search_id="search-0001",
            merchant_id="merchant-a",
            mode=Mode.LIVE,
            lines=(a_line(), a_line(merchant="merchant-b")),
        )


def test_an_unknown_fee_makes_the_basket_total_unknown() -> None:
    basket = build_basket(
        basket_id="basket-0001",
        search_id="search-0001",
        merchant_id="merchant-a",
        mode=Mode.LIVE,
        lines=(a_line(),),
        fee_assessment=a_fee_assessment(Charge.unknown_charge(ChargeKind.DELIVERY)),
    )
    assert basket.totals.total is None
    assert basket.totals.unknown_charges == (ChargeKind.DELIVERY,)


def test_a_fee_assessment_has_no_per_line_field() -> None:
    """Fees are basket-level, so a delivery charge cannot be counted twice."""
    assert "item_id" not in FeeAssessment.model_fields
    assert "line_id" not in FeeAssessment.model_fields


def test_a_substitution_is_visible_on_the_line() -> None:
    line = a_line().model_copy(
        update={
            "substitution": Substitution(
                kind=SubstitutionKind.BRAND, requested="India Gate", supplied="Daawat"
            )
        }
    )
    assert line.is_substituted


# -- quote -----------------------------------------------------------------


def a_quote_line(paise: int = 60_000) -> QuoteLine:
    return QuoteLine(
        sku="sku-00001",
        name="Basmati rice 1kg",
        quantity_base=5000,
        dimension="mass",
        unit_price=Money.paise(12_000),
        line_total=Money.paise(paise),
    )


def a_quote(**overrides: Any) -> CheckoutQuote:
    lines = (a_quote_line(),)
    charges = (Charge.known_charge(ChargeKind.DELIVERY, Money.paise(2_000)),)
    base: dict[str, Any] = {
        "quote_id": "quote-00000001",
        "purchase_id": "purchase-0001",
        "owner_id": "owner-0001",
        "purchase_version": 1,
        "quote_version": 1,
        "demo_seller_id": "demo-seller-01",
        "source_merchant_id": "merchant-a",
        "mode": Mode.LIVE,
        "lines": lines,
        "charges": charges,
        "total": Money.paise(62_000),
        "currency": Currency.INR,
        "delivery": "standard",
        "issued_at": NOW,
        "expires_at": EXPIRY,
    }
    base.update(overrides)
    base["quote_hash"] = quote_hash(
        owner_id=base["owner_id"],
        purchase_id=base["purchase_id"],
        purchase_version=base["purchase_version"],
        quote_id=base["quote_id"],
        quote_version=base["quote_version"],
        seller_id=base["demo_seller_id"],
        source_merchant_id=base["source_merchant_id"],
        mode=base["mode"],
        lines=base["lines"],
        charges=base["charges"],
        currency=base["currency"],
        delivery=base["delivery"],
        expires_at=base["expires_at"],
    )
    return CheckoutQuote(**base)


def test_a_quote_verifies_against_its_own_hash() -> None:
    quote = a_quote()
    assert quote.verify(quote.quote_hash) is None


def test_a_submitted_hash_that_differs_is_refused() -> None:
    quote = a_quote()
    mismatch = quote.verify("f" * 64)
    assert mismatch is not None
    assert mismatch.expected == quote.quote_hash


def test_a_stored_quote_that_no_longer_matches_its_hash_is_caught() -> None:
    """Catches a corrupted record with the same check as a tampered payload."""
    quote = a_quote()
    tampered = quote.model_copy(update={"total": Money.paise(62_000), "delivery": "express"})
    assert tampered.verify(tampered.quote_hash) is not None


def test_a_quote_total_must_equal_its_parts() -> None:
    with pytest.raises(ValidationError, match="does not equal the sum"):
        a_quote(total=Money.paise(1))


def test_a_quote_cannot_carry_an_unknown_charge() -> None:
    """An unknown fee has no ceiling, so no amount on the control is true."""
    # Total set to the lines alone, so the sum guard is satisfied and the
    # ceiling guard is demonstrably the one doing the rejecting.
    with pytest.raises(ValidationError, match="no ceiling"):
        a_quote(
            charges=(Charge.unknown_charge(ChargeKind.DELIVERY),),
            total=Money.paise(60_000),
        )


def test_a_quote_may_carry_an_estimated_charge_and_reports_it_as_a_ceiling() -> None:
    """WP-02-A1: estimated is quotable, and the quote says so itself.

    ``total_confidence`` is what the approval label reads to decide between
    "Approve simulated Rs X" and "Approve simulated up to Rs X", so a quote that
    carries an estimate must report it rather than look exact.
    """
    quote = a_quote(
        charges=(Charge.known_charge(ChargeKind.SURGE, Money.paise(2_000), Confidence.ESTIMATED),)
    )
    assert quote.total_confidence is Confidence.ESTIMATED


def test_a_fixture_quote_hashes_differently_from_an_identical_live_one() -> None:
    assert a_quote(mode=Mode.LIVE).quote_hash != a_quote(mode=Mode.FIXTURE).quote_hash


def test_a_quote_is_immutable() -> None:
    with pytest.raises(ValidationError):
        a_quote().total = Money.paise(1)  # type: ignore[misc]


# -- approval --------------------------------------------------------------


def an_approval(**overrides: Any) -> Approval:
    quote = a_quote()
    base: dict[str, Any] = {
        "approval_id": approval_id(
            quote_id=quote.quote_id, quote_hash=quote.quote_hash, quote_version=1
        ),
        "quote_id": quote.quote_id,
        "quote_hash": quote.quote_hash,
        "quote_version": 1,
        "purchase_version": 1,
        "owner_id": "owner-0001",
    }
    base.update(overrides)
    return Approval(**base)


def test_a_consumed_approval_must_name_its_attempt() -> None:
    with pytest.raises(ValidationError, match="names its attempt"):
        an_approval(status=ApprovalState.CONSUMED)


def test_an_unconsumed_approval_cannot_name_an_attempt() -> None:
    with pytest.raises(ValidationError):
        an_approval(consumed_attempt_id="attempt-0001")


def test_the_same_quote_always_yields_the_same_approval_id() -> None:
    assert an_approval().approval_id == an_approval().approval_id


# -- attempt and provider lookup ------------------------------------------


def test_the_dispatch_marker_and_its_timestamp_cannot_disagree() -> None:
    """After a crash, the ambiguity window has to be readable."""
    with pytest.raises(ValidationError, match="must agree"):
        Attempt(
            attempt_id="attempt-0001",
            purchase_id="purchase-0001",
            approval_id="a" * 64,
            payment_key="b" * 64,
            request_hash="c" * 64,
            dispatch=DispatchState.STARTED,
        )
    with pytest.raises(ValidationError, match="must agree"):
        Attempt(
            attempt_id="attempt-0001",
            purchase_id="purchase-0001",
            approval_id="a" * 64,
            payment_key="b" * 64,
            request_hash="c" * 64,
            dispatch=DispatchState.READY,
            started_at=NOW,
        )


def a_purchase(**overrides: Any) -> Purchase:
    base: dict[str, Any] = {
        "purchase_id": "purchase-0001",
        "owner_id": "owner-0001",
        "basket_id": "basket-0001",
        "intent_revision": 1,
        "mode": Mode.LIVE,
    }
    base.update(overrides)
    return Purchase(**base)


def test_an_attempt_and_its_lookup_are_derived_from_consent() -> None:
    quote = a_quote()
    approval = an_approval()
    attempt, lookup = build_attempt_and_lookup(
        attempt_id="attempt-0001",
        purchase=a_purchase(),
        approval=approval,
        quote=quote,
    )
    assert attempt.payment_key == payment_key(
        purchase_id="purchase-0001", approval_id=approval.approval_id
    )
    assert lookup.payment_key == attempt.payment_key
    assert lookup.expected_amount == quote.total
    assert lookup.unique_key == f"PROVIDER#sim#{attempt.payment_key}"


def test_building_the_attempt_twice_is_replay_safe() -> None:
    """Two concurrent approvals of one quote produce one key, not two."""
    args = {
        "attempt_id": "attempt-0001",
        "purchase": a_purchase(),
        "approval": an_approval(),
        "quote": a_quote(),
    }
    first, first_lookup = build_attempt_and_lookup(**args)  # type: ignore[arg-type]
    second, second_lookup = build_attempt_and_lookup(**args)  # type: ignore[arg-type]
    assert first == second
    assert first_lookup == second_lookup


def test_a_lookup_matches_only_the_terms_that_were_approved() -> None:
    quote = a_quote()
    _, lookup = build_attempt_and_lookup(
        attempt_id="attempt-0001",
        purchase=a_purchase(),
        approval=an_approval(),
        quote=quote,
    )
    assert lookup.matches(seller_id="demo-seller-01", amount=quote.total, currency=Currency.INR)
    # A callback claiming a different amount must never become truth.
    assert not lookup.matches(
        seller_id="demo-seller-01", amount=Money.paise(1), currency=Currency.INR
    )
    assert not lookup.matches(seller_id="someone-else", amount=quote.total, currency=Currency.INR)


# -- purchase --------------------------------------------------------------


def test_a_claim_and_an_active_attempt_must_agree() -> None:
    with pytest.raises(ValidationError, match="names its active attempt"):
        a_purchase(claim=ClaimState.CLAIMED)
    with pytest.raises(ValidationError, match="requires the purchase to be claimed"):
        a_purchase(active_attempt_id="attempt-0001")


def test_payment_success_alone_is_not_resolution() -> None:
    """SPEC section 8: resolution needs order or refund evidence too."""
    paid_no_order = a_purchase(payment=PaymentState.SUCCEEDED)
    assert paid_no_order.is_resolved is False

    paid_and_ordered = a_purchase(payment=PaymentState.SUCCEEDED, order=OrderState.CONFIRMED)
    assert paid_and_ordered.is_resolved is True


def test_a_definitively_failed_payment_is_resolved() -> None:
    assert a_purchase(payment=PaymentState.FAILED).is_resolved is True


def test_an_unknown_payment_is_not_resolved() -> None:
    assert a_purchase(payment=PaymentState.UNKNOWN).is_resolved is False


def test_the_three_outcomes_default_to_their_own_initial_states() -> None:
    purchase = a_purchase()
    assert purchase.payment is PaymentState.NOT_STARTED
    assert purchase.order is OrderState.NOT_CREATED
    assert purchase.refund.value == "none"
