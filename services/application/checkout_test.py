"""The checkout task (WP-09 acceptance criteria 1, 2, 3, 6, 7, 8).

The headline: one approval produces exactly one provider effect, across a lost
response, reloads, retries and resends. Proven by counting the provider's own
ledger, not by reading our state.
"""

from __future__ import annotations

import pytest

from services.application.callbacks import Disposition
from services.application.checkout import (
    OBSERVATION_WINDOW_SECONDS,
    POLL_SCHEDULE,
    CheckoutOutcome,
    CheckoutTask,
)
from services.application.fakes import SequentialIds
from services.application.ports import ConditionFailed, Write, read
from services.application.prepare_test import (
    OWNER,
    PURCHASE_ID,
    World,
    merchant_selling,
)
from services.application.provider_ports import (
    OrderFacts,
    OrderRequest,
    PaymentFacts,
    ProviderConflict,
    ProviderNotFound,
    ProviderWritePort,
    ResponseLost,
    SubmitRequest,
)
from services.application.purchase import AttemptCreated, attempt_key
from services.domain.errors import DomainError
from services.domain.purchase import Attempt
from services.domain.transitions import DispatchState, OrderState, PaymentState
from services.simulator.adapter import SimulatorProvider
from services.simulator.ledger import Scenario
from services.simulator.operations import Simulator


class Checkout:
    """A world that has been prepared, quoted and approved, ready to pay."""

    def __init__(self, scenario: Scenario = Scenario.SUCCESS) -> None:
        self.world = World()
        _prep, diff = self.world.prepare_ok(merchant_selling(59_500))
        self.quote = self.world.accept_ok(diff.hash()).quote
        approved = self.world.uc.approve(
            owner_id=OWNER,
            purchase_id=PURCHASE_ID,
            quote_id=self.quote.quote_id,
            quote_hash=self.quote.quote_hash,
            quote_version=self.quote.quote_version,
            expected_purchase_version=self.world.purchase_row().version,
            idempotency="idem-1",
        )
        assert isinstance(approved, AttemptCreated), f"approve failed: {approved}"
        self.attempt_id = approved.attempt_id
        self.simulator = Simulator(clock=self.world.clock, ids=SequentialIds(), scenario=scenario)
        self.provider: ProviderWritePort = SimulatorProvider(self.simulator)
        #: Callback dispositions observed by scenario tests that drive ingestion
        #: through this world. Declared here so it is part of the harness rather
        #: than an attribute bolted on from another module.
        self.dispositions: list[Disposition] = []
        self.task = CheckoutTask(
            store=self.world.store, clock=self.world.clock, provider=self.provider
        )

    def run(self) -> CheckoutOutcome | DomainError:
        """Drive the steps to a conclusion, the way the workflow will."""
        return self.task.run_to_completion(purchase_id=PURCHASE_ID, attempt_id=self.attempt_id)

    def step(self) -> CheckoutOutcome | DomainError:
        return self.task.step(purchase_id=PURCHASE_ID, attempt_id=self.attempt_id)

    def run_ok(self) -> CheckoutOutcome:
        """Run to completion, asserting it concluded. For tests about the outcome."""
        outcome = self.run()
        assert isinstance(outcome, CheckoutOutcome), f"checkout failed: {outcome}"
        return outcome

    def step_ok(self) -> CheckoutOutcome:
        outcome = self.step()
        assert isinstance(outcome, CheckoutOutcome), f"step failed: {outcome}"
        return outcome

    def attempt_row(self, attempt_id: str) -> Attempt:
        found = read(self.world.store, attempt_key(PURCHASE_ID, attempt_id), Attempt)
        assert found is not None, "the attempt should exist"
        return found

    def attempt(self) -> Attempt:
        found = read(self.world.store, attempt_key(PURCHASE_ID, self.attempt_id), Attempt)
        assert found is not None, "the attempt should exist"
        return found


# -- the marker goes down before the call ----------------------------------


def test_dispatch_is_persisted_started_before_the_provider_is_called() -> None:
    """Asserted by call ordering, not by reading the code.

    If the marker were written after the call, a crash between them would leave
    the attempt looking untouched and a retry would pay twice.
    """
    checkout = Checkout()
    order_of_events: list[str] = []

    real_transact = checkout.world.store.transact
    real_submit = checkout.provider.submit

    def watched_transact(writes: list[Write]) -> None | ConditionFailed:
        if any("ATTEMPT#" in key[1] for key in (w.key for w in writes)):
            order_of_events.append("dispatch_started_persisted")
        return real_transact(writes)

    def watched_submit(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        order_of_events.append("provider_called")
        return real_submit(request)

    checkout.world.store.transact = watched_transact  # type: ignore[method-assign]
    checkout.provider.submit = watched_submit  # type: ignore[method-assign]
    checkout.run()

    assert order_of_events[0] == "dispatch_started_persisted"
    assert "provider_called" in order_of_events
    assert order_of_events.index("dispatch_started_persisted") < order_of_events.index(
        "provider_called"
    )


def test_the_attempt_records_when_the_call_started() -> None:
    checkout = Checkout()
    checkout.run()
    attempt = checkout.attempt()
    assert attempt.dispatch is DispatchState.STARTED
    assert attempt.started_at is not None


# -- the happy path --------------------------------------------------------


def test_a_successful_payment_creates_one_order_and_one_effect() -> None:
    checkout = Checkout(Scenario.SUCCESS)
    outcome = checkout.run()
    assert isinstance(outcome, CheckoutOutcome)
    assert outcome.payment is PaymentState.SUCCEEDED
    assert outcome.order is OrderState.CONFIRMED
    assert checkout.simulator.effect_count() == 1
    assert checkout.simulator.order_effect_count() == 1


def test_a_definitive_failure_creates_no_order() -> None:
    checkout = Checkout(Scenario.DEFINITIVE_FAILURE)
    outcome = checkout.run_ok()
    assert outcome.payment is PaymentState.FAILED
    assert outcome.order is OrderState.NOT_CREATED
    assert checkout.simulator.order_effect_count() == 0


def test_an_order_is_never_created_before_the_payment_succeeds() -> None:
    """Asserted by watching the provider, not by trusting the branch."""
    checkout = Checkout(Scenario.DEFINITIVE_FAILURE)
    calls: list[str] = []
    real_create = checkout.provider.create_order

    def watched(request: OrderRequest) -> OrderFacts | ProviderNotFound:
        calls.append(request.order_key)
        return real_create(request)

    checkout.provider.create_order = watched  # type: ignore[method-assign]
    checkout.run()
    assert calls == []


# -- the scenario the product exists for -----------------------------------


def test_a_lost_response_leaves_the_payment_unknown_not_failed() -> None:
    checkout = Checkout(Scenario.ACCEPT_THEN_TIMEOUT)
    outcome = checkout.run_ok()
    # The task recovers by querying, so it resolves -- but never by guessing.
    # The name of this test is the first assertion: a lost response is not a
    # failure. The second says what it may legitimately be instead.
    assert outcome.payment is not PaymentState.FAILED
    assert outcome.payment in (PaymentState.SUCCEEDED, PaymentState.UNKNOWN)


def test_accept_then_timeout_still_records_exactly_one_effect() -> None:
    checkout = Checkout(Scenario.ACCEPT_THEN_TIMEOUT)
    checkout.run()
    assert checkout.simulator.effect_count() == 1


def test_running_the_task_repeatedly_never_pays_twice() -> None:
    """A retried job, a duplicate delivery, an impatient operator."""
    checkout = Checkout(Scenario.ACCEPT_THEN_TIMEOUT)
    for _ in range(5):
        checkout.run()
    assert checkout.simulator.effect_count() == 1


def test_a_resend_uses_the_identical_payload() -> None:
    checkout = Checkout(Scenario.ACCEPT_THEN_TIMEOUT)
    seen: list[SubmitRequest] = []
    real_submit = checkout.provider.submit

    def watched(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        seen.append(request)
        return real_submit(request)

    checkout.provider.submit = watched  # type: ignore[method-assign]
    checkout.run()

    assert len(seen) >= 1
    assert len({(r.payment_key, r.request_hash, r.amount, r.expires_at) for r in seen}) == 1


def test_paid_but_no_order_opens_a_case_and_keeps_the_payment_succeeded() -> None:
    checkout = Checkout(Scenario.PAID_ORDER_MISSING)
    outcome = checkout.run_ok()
    assert outcome.payment is PaymentState.SUCCEEDED
    assert outcome.order is OrderState.NOT_CREATED
    assert outcome.case_opened is True
    assert checkout.simulator.effect_count() == 1
    assert checkout.simulator.order_effect_count() == 0


# -- a failed job is not a failed payment ----------------------------------


def test_an_unresolved_window_still_reports_the_job_as_succeeded() -> None:
    """The task did its work. The money is a separate question."""
    checkout = Checkout()

    def never_answers(*, payment_key: str) -> PaymentFacts | ProviderNotFound:
        return ProviderNotFound(key="a")

    def never_accepts(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        raise ResponseLost("a" * 64)

    checkout.provider.submit = never_accepts  # type: ignore[method-assign]
    checkout.provider.query_payment = never_answers  # type: ignore[method-assign]
    checkout.provider.effect_count = lambda: 0  # type: ignore[method-assign]

    outcome = checkout.run_ok()
    assert outcome.payment is PaymentState.UNKNOWN
    assert outcome.job_succeeded is True
    assert outcome.case_opened is True


def test_the_outcome_keeps_job_and_payment_as_separate_fields() -> None:
    """So no caller can accidentally render one as the other."""
    fields = set(CheckoutOutcome.model_fields)
    assert {"payment", "order", "job_succeeded"} <= fields


# -- expiry before dispatch ------------------------------------------------


def test_an_expired_quote_is_never_sent() -> None:
    checkout = Checkout()
    checkout.world.clock.advance(121)
    calls: list[object] = []

    def record(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        calls.append(request)
        raise ResponseLost("a" * 64)

    checkout.provider.submit = record  # type: ignore[method-assign]

    outcome = checkout.run_ok()
    assert calls == [], "nothing may be sent after the quote expires"
    assert outcome.payment is PaymentState.NOT_STARTED
    assert checkout.attempt().dispatch is DispatchState.EXPIRED_UNSENT


def test_an_already_expired_attempt_is_a_no_op() -> None:
    checkout = Checkout()
    checkout.world.clock.advance(121)
    checkout.run()
    second = checkout.run_ok()
    assert second.payment is PaymentState.NOT_STARTED
    assert checkout.simulator.effect_count() == 0


def test_expiry_does_not_touch_an_attempt_that_already_started() -> None:
    """Once a provider has been called, only facts decide -- never the clock."""
    checkout = Checkout()
    checkout.run()
    assert checkout.attempt().dispatch is DispatchState.STARTED

    checkout.world.clock.advance(10_000)
    checkout.run()
    assert checkout.attempt().dispatch is DispatchState.STARTED


# -- matching --------------------------------------------------------------


def test_facts_about_a_different_amount_are_never_applied() -> None:
    checkout = Checkout()
    from services.application.provider_ports import PaymentFacts, ProviderPaymentStatus
    from services.domain.money import Money

    wrong = PaymentFacts(
        payment_key="a" * 64,
        status=ProviderPaymentStatus.SUCCEEDED,
        provider_reference="payref-1",
        seller_id="demo-seller-01",
        amount=Money.paise(1),
    )

    def answer_wrong(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        return wrong

    checkout.provider.submit = answer_wrong  # type: ignore[method-assign]

    outcome = checkout.run_ok()
    assert outcome.payment is PaymentState.UNKNOWN
    assert outcome.case_opened is True
    assert "did not match" in outcome.detail


# -- the schedule ----------------------------------------------------------


def test_the_poll_schedule_is_what_the_spec_says() -> None:
    assert POLL_SCHEDULE == (5, 10, 20, 30)
    assert OBSERVATION_WINDOW_SECONDS == 180


def test_the_window_is_measured_from_when_dispatch_started() -> None:
    """Behavioural, not a source-text check: move the clock past the window."""
    checkout = Checkout()

    def never_found(*, payment_key: str) -> PaymentFacts | ProviderNotFound:
        return ProviderNotFound(key="a")

    def lost(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        raise ResponseLost("a" * 64)

    checkout.provider.submit = lost  # type: ignore[method-assign]
    checkout.provider.query_payment = never_found  # type: ignore[method-assign]

    first = checkout.step_ok()
    assert first.next_check_at is not None, "still inside the window"

    checkout.world.clock.advance(OBSERVATION_WINDOW_SECONDS + 1)
    closed = checkout.step_ok()
    assert closed.stage == "window_closed"
    assert closed.is_final is True


def test_polling_stops_rather_than_running_forever() -> None:
    checkout = Checkout()

    def never_found(*, payment_key: str) -> PaymentFacts | ProviderNotFound:
        return ProviderNotFound(key="a")

    def lost(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        raise ResponseLost("a" * 64)

    checkout.provider.submit = lost  # type: ignore[method-assign]
    checkout.provider.query_payment = never_found  # type: ignore[method-assign]
    checkout.provider.effect_count = lambda: 0  # type: ignore[method-assign]

    outcome = checkout.run_ok()
    assert outcome.stage == "window_closed"
    assert outcome.payment is PaymentState.UNKNOWN


# -- guards ----------------------------------------------------------------


def test_a_payment_is_never_submitted_without_a_lookup_row() -> None:
    """Otherwise a returning callback could not be matched to anything."""
    from services.application.purchase import provider_lookup_key
    from services.domain.errors import InvalidRecord

    checkout = Checkout()
    attempt = checkout.attempt()
    checkout.world.memory._items.pop(provider_lookup_key(attempt.payment_key))

    calls: list[object] = []

    def record(request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        calls.append(request)
        raise ResponseLost("a" * 64)

    checkout.provider.submit = record  # type: ignore[method-assign]

    result = checkout.run()
    assert isinstance(result, InvalidRecord)
    assert calls == []


@pytest.mark.parametrize("scenario", list(Scenario))
def test_no_scenario_ever_produces_two_effects(scenario: Scenario) -> None:
    checkout = Checkout(scenario)
    for _ in range(3):
        checkout.run()
    assert checkout.simulator.effect_count() <= 1
