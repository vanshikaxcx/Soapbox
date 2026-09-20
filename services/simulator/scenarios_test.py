"""Every fault scenario the POA requires, driven end to end (WP-09).

The POA's evidence list for WP-09 names seven: success, definitive failure,
expiry before dispatch, crash after dispatch, accept-then-timeout,
paid/order-missing, duplicate/conflicting callback and refund pending->complete.

Three of those used to exist only as enum values -- the simulator ignored them
entirely, so they behaved exactly like success. These tests drive each one all
the way through the real checkout task and the real callback ingestion, and
assert the outcomes are actually distinguishable.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.application.callbacks import Disposition
from services.application.cases import CallbackIngest, case_key
from services.application.checkout import CheckoutTask
from services.application.checkout_test import Checkout
from services.application.fakes import SequentialIds
from services.domain.purchase import Purchase
from services.domain.transitions import (
    DispatchState,
    OrderState,
    PaymentState,
    RefundState,
)
from services.simulator.callback_sender import CallbackSender
from services.simulator.ledger import PaymentRecord, Scenario

PURCHASE_ID = "purchase-0001"
SECRET = b"a-rotated-secret-from-secrets-manager"


def _drive(scenario: Scenario, *, deliver: bool = True) -> Checkout:
    """Run a scenario through checkout, then through its callbacks."""
    checkout = Checkout(scenario)
    ingest = CallbackIngest(
        store=checkout.world.store, clock=checkout.world.clock, ids=SequentialIds(), secret=SECRET
    )
    checkout.task = CheckoutTask(
        store=checkout.world.store,
        clock=checkout.world.clock,
        provider=checkout.provider,
        cases=ingest._cases,  # the same service the ingest path uses
    )
    checkout.run()
    checkout.dispositions.clear()

    if deliver:
        sender = CallbackSender(secret=SECRET)
        attempt = checkout.attempt_row(checkout.attempt_id)
        payment = checkout.simulator.query(payment_key=attempt.payment_key)
        if isinstance(payment, PaymentRecord):
            now = checkout.world.clock.now()
            for delivery in sender.deliveries_for(payment, at=now, scenario=scenario):
                result = ingest.ingest(
                    headers=delivery.headers, raw_body=delivery.raw_body, body=delivery.body
                )
                if result.disposition is not None:
                    checkout.dispositions.append(result.disposition)
    return checkout


def _purchase(checkout: Checkout) -> Purchase:
    return checkout.world.purchase_row()


# -- each scenario is genuinely distinguishable ----------------------------


def test_success_pays_and_orders() -> None:
    checkout = _drive(Scenario.SUCCESS)
    purchase = _purchase(checkout)
    assert purchase.payment is PaymentState.SUCCEEDED
    assert purchase.order is OrderState.CONFIRMED
    assert checkout.simulator.effect_count() == 1


def test_definitive_failure_pays_nothing_and_orders_nothing() -> None:
    checkout = _drive(Scenario.DEFINITIVE_FAILURE)
    purchase = _purchase(checkout)
    assert purchase.payment is PaymentState.FAILED
    assert purchase.order is OrderState.NOT_CREATED
    assert checkout.simulator.order_effect_count() == 0


def test_expiry_before_dispatch_never_calls_the_provider() -> None:
    checkout = Checkout()
    checkout.world.clock.advance(121)
    checkout.run()
    attempt = checkout.attempt_row(checkout.attempt_id)
    assert attempt.dispatch is DispatchState.EXPIRED_UNSENT
    assert checkout.simulator.effect_count() == 0


def test_a_crash_after_dispatch_leaves_an_ambiguous_attempt() -> None:
    """The process dies between the marker and any answer.

    Resuming finds ``started`` with no facts -- which is the honest state, and
    exactly why the marker is written before the call.
    """
    checkout = Checkout(Scenario.ACCEPT_THEN_TIMEOUT)
    checkout.step()  # marks started, submits, loses the reply

    attempt = checkout.attempt_row(checkout.attempt_id)
    assert attempt.dispatch is DispatchState.STARTED
    assert _purchase(checkout).payment is PaymentState.UNKNOWN
    assert checkout.simulator.effect_count() == 1, "the money moved regardless"


def test_accept_then_timeout_resolves_by_asking_not_by_paying_again() -> None:
    checkout = _drive(Scenario.ACCEPT_THEN_TIMEOUT)
    assert _purchase(checkout).payment is PaymentState.SUCCEEDED
    assert checkout.simulator.effect_count() == 1


def test_paid_order_missing_opens_a_case() -> None:
    checkout = _drive(Scenario.PAID_ORDER_MISSING)
    purchase = _purchase(checkout)
    assert purchase.payment is PaymentState.SUCCEEDED
    assert purchase.order is OrderState.NOT_CREATED
    assert checkout.world.store.get(case_key(PURCHASE_ID)) is not None


# -- the three that used to do nothing -------------------------------------


def test_duplicate_callback_is_applied_once() -> None:
    """The provider retried because it never saw our 2xx."""
    checkout = _drive(Scenario.DUPLICATE_CALLBACK)
    assert checkout.dispositions == [Disposition.APPLIED, Disposition.DUPLICATE]
    assert _purchase(checkout).payment is PaymentState.SUCCEEDED


def test_conflicting_callback_is_never_applied() -> None:
    """One event id, two different bodies. The second is refused outright."""
    checkout = _drive(Scenario.CONFLICTING_CALLBACK)
    assert checkout.dispositions == [Disposition.APPLIED, Disposition.CONFLICTED]
    # The lie claimed the payment failed. It did not take.
    assert _purchase(checkout).payment is PaymentState.SUCCEEDED


def test_a_refund_arrives_pending_then_completed() -> None:
    """ProofPath never asked for it. Refunds appear only as provider facts."""
    checkout = _drive(Scenario.REFUND_PENDING_THEN_COMPLETE)
    purchase = _purchase(checkout)
    assert purchase.refund is RefundState.COMPLETED
    assert purchase.payment is PaymentState.SUCCEEDED, "the payment is untouched"


def test_the_refund_passes_through_pending_on_the_way() -> None:
    checkout = Checkout(Scenario.REFUND_PENDING_THEN_COMPLETE)
    ingest = CallbackIngest(
        store=checkout.world.store, clock=checkout.world.clock, ids=SequentialIds(), secret=SECRET
    )
    checkout.run()
    attempt = checkout.attempt_row(checkout.attempt_id)
    payment = checkout.simulator.query(payment_key=attempt.payment_key)
    assert isinstance(payment, PaymentRecord), "the scenario should have paid"

    sender = CallbackSender(secret=SECRET)
    deliveries = sender.deliveries_for(
        payment,
        at=checkout.world.clock.now(),
        scenario=Scenario.REFUND_PENDING_THEN_COMPLETE,
    )
    states = []
    for delivery in deliveries:
        ingest.ingest(headers=delivery.headers, raw_body=delivery.raw_body, body=delivery.body)
        states.append(_purchase(checkout).refund)

    assert RefundState.PENDING in states
    assert states[-1] is RefundState.COMPLETED


def test_an_old_pending_refund_cannot_undo_a_completed_one() -> None:
    """The same stickiness that protects payments protects refunds."""
    checkout = Checkout(Scenario.REFUND_PENDING_THEN_COMPLETE)
    ingest = CallbackIngest(
        store=checkout.world.store, clock=checkout.world.clock, ids=SequentialIds(), secret=SECRET
    )
    checkout.run()
    attempt = checkout.attempt_row(checkout.attempt_id)
    payment = checkout.simulator.query(payment_key=attempt.payment_key)
    assert isinstance(payment, PaymentRecord), "the scenario should have paid"
    sender = CallbackSender(secret=SECRET)

    now = checkout.world.clock.now()
    deliveries = sender.deliveries_for(
        payment, at=now, scenario=Scenario.REFUND_PENDING_THEN_COMPLETE
    )
    for delivery in deliveries:
        ingest.ingest(headers=delivery.headers, raw_body=delivery.raw_body, body=delivery.body)
    assert _purchase(checkout).refund is RefundState.COMPLETED

    # Now a stale 'pending' arrives late, with a fresh event id.
    stale = sender._refund_delivery(
        payment, at=now + timedelta(seconds=1), event_id="evt-refund-late", status="pending"
    )
    ingest.ingest(headers=stale.headers, raw_body=stale.raw_body, body=stale.body)
    assert _purchase(checkout).refund is RefundState.COMPLETED


# -- and the claim across all of them --------------------------------------


@pytest.mark.parametrize("scenario", list(Scenario))
def test_every_scenario_produces_at_most_one_payment_effect(
    scenario: Scenario,
) -> None:
    checkout = _drive(scenario)
    assert checkout.simulator.effect_count() <= 1


def test_the_seven_scenarios_are_not_all_the_same_thing() -> None:
    """The gap that started this: three of them used to behave like success."""
    outcomes = {}
    for scenario in Scenario:
        checkout = _drive(scenario)
        purchase = _purchase(checkout)
        outcomes[scenario] = (
            purchase.payment,
            purchase.order,
            purchase.refund,
            tuple(checkout.dispositions),
        )
    assert len(set(outcomes.values())) >= 5, (
        f"scenarios collapsed into {len(set(outcomes.values()))} distinct outcomes"
    )
