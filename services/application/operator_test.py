"""Operator controls, effect counts and reconciliation (WP-09 criteria 14-17)."""

from __future__ import annotations

import pytest

from services.application.checkout_test import Checkout
from services.application.operator import EffectCounts, OperatorUseCases, ScenarioSet
from services.application.provider_ports import (
    OrderFacts,
    PaymentFacts,
    ProviderConflict,
    ProviderNotFound,
    ResponseLost,
    SubmitRequest,
)
from services.application.purchase import NotFound
from services.application.reconcile import ReconcileTask, Reconciliation
from services.domain.transitions import OrderState, PaymentState
from services.simulator.adapter import ReadOnlyProvider
from services.simulator.ledger import Scenario

PURCHASE_ID = "purchase-0001"
OPERATOR = "operator-0001"
SHOPPER = "owner-0001"


class OperatorPolicy:
    """One operator, everyone else a shopper."""

    def is_operator(self, owner_id: str) -> bool:
        return owner_id == OPERATOR


def an_operator(checkout: Checkout) -> OperatorUseCases[Scenario]:
    return OperatorUseCases(
        store=checkout.world.store, simulator=checkout.simulator, policy=OperatorPolicy()
    )


def counts_for(checkout: Checkout) -> EffectCounts:
    """The operator's counts, asserting the caller was allowed to read them."""
    counts = an_operator(checkout).effect_counts(owner_id=OPERATOR)
    assert isinstance(counts, EffectCounts), f"operator was refused: {counts}"
    return counts


# -- authorization ---------------------------------------------------------


def test_an_operator_can_set_a_scenario() -> None:
    checkout = Checkout()
    result = an_operator(checkout).set_scenario(
        owner_id=OPERATOR, scenario=Scenario.PAID_ORDER_MISSING
    )
    assert isinstance(result, ScenarioSet)
    assert checkout.simulator.scenario is Scenario.PAID_ORDER_MISSING


def test_a_shopper_gets_not_found_rather_than_forbidden() -> None:
    """Telling someone a control exists but is not theirs still tells them."""
    checkout = Checkout()
    result = an_operator(checkout).set_scenario(
        owner_id=SHOPPER, scenario=Scenario.DEFINITIVE_FAILURE
    )
    assert isinstance(result, NotFound)
    assert checkout.simulator.scenario is Scenario.SUCCESS, "nothing changed"


def test_a_shopper_cannot_read_effect_counts_either() -> None:
    checkout = Checkout()
    assert isinstance(an_operator(checkout).effect_counts(owner_id=SHOPPER), NotFound)


def test_authorization_is_checked_before_anything_happens() -> None:
    checkout = Checkout()
    before = checkout.simulator.scenario
    an_operator(checkout).set_scenario(owner_id=SHOPPER, scenario=Scenario.SUCCESS)
    assert checkout.simulator.scenario is before


# -- the number the demo turns on -----------------------------------------


def test_effect_counts_come_from_the_providers_own_ledger() -> None:
    checkout = Checkout(Scenario.SUCCESS)
    checkout.run_ok()
    counts = counts_for(checkout)
    assert isinstance(counts, EffectCounts)
    assert counts.payment_effects == 1
    assert counts.order_effects == 1


def test_one_approval_yields_one_effect_and_one_dispatch() -> None:
    """Criterion 17, asserted rather than eyeballed during the demo."""
    checkout = Checkout(Scenario.SUCCESS)
    checkout.run_ok()
    counts = counts_for(checkout)
    assert counts.attempts_dispatched == 1
    assert counts.payment_effects == counts.attempts_dispatched
    assert counts.one_effect_per_attempt is True


@pytest.mark.parametrize("scenario", list(Scenario))
def test_effects_never_exceed_dispatches_in_any_scenario(scenario: Scenario) -> None:
    checkout = Checkout(scenario)
    for _ in range(3):
        checkout.run_ok()
    counts = counts_for(checkout)
    assert counts.payment_effects <= counts.attempts_dispatched


def test_repeated_runs_do_not_inflate_the_dispatch_count() -> None:
    checkout = Checkout(Scenario.ACCEPT_THEN_TIMEOUT)
    for _ in range(5):
        checkout.run_ok()
    counts = counts_for(checkout)
    assert counts.attempts_dispatched == 1
    assert counts.payment_effects == 1


def test_an_expired_attempt_counts_as_neither() -> None:
    checkout = Checkout()
    checkout.world.clock.advance(121)
    checkout.run_ok()
    counts = counts_for(checkout)
    assert counts.attempts_dispatched == 0
    assert counts.payment_effects == 0


def test_duplicate_submissions_are_counted_separately_from_effects() -> None:
    """Resends are expected. Effects are not."""
    checkout = Checkout(Scenario.ACCEPT_THEN_TIMEOUT)
    checkout.run_ok()
    counts = counts_for(checkout)
    assert counts.submissions_received >= counts.payment_effects


# -- reconciliation --------------------------------------------------------


def a_reconciler(checkout: Checkout) -> ReconcileTask:
    """Deliberately handed the READ-ONLY provider."""
    return ReconcileTask(
        store=checkout.world.store,
        clock=checkout.world.clock,
        provider=ReadOnlyProvider(checkout.provider),
    )


def test_reconcile_finds_a_payment_the_task_never_saw() -> None:
    """The ambiguity resolved later, by asking rather than by guessing."""
    checkout = Checkout(Scenario.SUCCESS)
    # Dispatch, then lose every answer so our own state stays unknown.
    real_submit = checkout.provider.submit

    def lost(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        real_submit(request)
        raise ResponseLost(request.payment_key)

    def not_found(*, payment_key: str) -> PaymentFacts | ProviderNotFound:
        return ProviderNotFound(key="a")

    checkout.provider.submit = lost  # type: ignore[method-assign]
    checkout.provider.query_payment = not_found  # type: ignore[method-assign]
    checkout.run_ok()

    stored = checkout.world.purchase_row()
    assert stored.payment is PaymentState.UNKNOWN

    # Now ask properly.
    checkout.provider.query_payment = SimulatorProviderQuery(checkout)  # type: ignore[method-assign]
    result = a_reconciler(checkout).run(owner_id=SHOPPER, purchase_id=PURCHASE_ID)
    assert isinstance(result, Reconciliation)
    assert result.payment is PaymentState.SUCCEEDED
    assert result.changed is True


class SimulatorProviderQuery:
    """Restores a real query after the test has broken it."""

    def __init__(self, checkout: Checkout) -> None:
        from services.simulator.adapter import SimulatorProvider

        self._real = SimulatorProvider(checkout.simulator)

    def __call__(self, *, payment_key: str) -> PaymentFacts | ProviderNotFound:
        return self._real.query_payment(payment_key=payment_key)


def test_reconcile_creates_nothing_when_the_order_is_missing() -> None:
    """Paid with no order is a fact to record, not a gap to fill."""
    checkout = Checkout(Scenario.PAID_ORDER_MISSING)
    checkout.run_ok()
    before = checkout.simulator.order_effect_count()

    result = a_reconciler(checkout).run(owner_id=SHOPPER, purchase_id=PURCHASE_ID)
    assert isinstance(result, Reconciliation)
    assert result.payment is PaymentState.SUCCEEDED
    assert result.order is OrderState.NOT_CREATED
    assert result.case_opened is True
    assert checkout.simulator.order_effect_count() == before


def test_reconcile_never_changes_the_provider_effect_count() -> None:
    for scenario in Scenario:
        checkout = Checkout(scenario)
        checkout.run_ok()
        before = checkout.simulator.effect_count()
        for _ in range(3):
            a_reconciler(checkout).run(owner_id=SHOPPER, purchase_id=PURCHASE_ID)
        assert checkout.simulator.effect_count() == before


def test_reconcile_is_refused_for_another_owner() -> None:
    checkout = Checkout()
    checkout.run_ok()
    result = a_reconciler(checkout).run(owner_id="owner-9999", purchase_id=PURCHASE_ID)
    assert isinstance(result, NotFound)


class NeverAsked:
    """A read port that must not be called."""

    def query_payment(self, *, payment_key: str) -> PaymentFacts | ProviderNotFound:
        raise AssertionError("the provider was queried when nothing was dispatched")

    def get_order(self, *, order_key: str) -> OrderFacts | ProviderNotFound:
        raise AssertionError("the provider was queried when nothing was dispatched")

    def query_refund(self, *, refund_reference: str) -> object | ProviderNotFound:
        raise AssertionError("the provider was queried when nothing was dispatched")


def test_reconcile_on_a_purchase_that_never_dispatched_says_so() -> None:
    from services.application.prepare_test import World

    world = World()
    # A provider that fails if touched, so this test proves the claim in its own
    # name: nothing was dispatched, so nothing is asked of the provider. Passing
    # None here would have relied on that rather than checked it.
    task = ReconcileTask(store=world.store, clock=world.clock, provider=NeverAsked())
    result = task.run(owner_id=SHOPPER, purchase_id=PURCHASE_ID)
    assert isinstance(result, Reconciliation)
    assert "nothing was ever dispatched" in result.detail


def test_reconcile_is_handed_a_port_with_no_write_verb() -> None:
    checkout = Checkout()
    provider = ReadOnlyProvider(checkout.provider)
    for verb in ("submit", "create_order"):
        assert not hasattr(provider, verb)
