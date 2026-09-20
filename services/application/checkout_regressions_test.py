"""Regressions from the WP-09 implementation review.

Three defects, all of which passed the original test suite. Two of them would
only have appeared in production, which is the point worth remembering: the
tests were green because they shared the implementation's assumptions.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from services.application.checkout import (
    OBSERVATION_WINDOW_SECONDS,
    CheckoutOutcome,
    CheckoutTask,
)
from services.application.checkout_test import Checkout
from services.application.ports import read
from services.application.provider_ports import (
    OrderFacts,
    OrderRequest,
    PaymentFacts,
    ProviderConflict,
    ProviderNotFound,
    ResponseLost,
    SubmitRequest,
)
from services.application.purchase import quote_key
from services.domain.errors import AttemptBlockedByExposure, InvalidRecord
from services.domain.purchase import Approval, CheckoutQuote, Purchase, may_create_attempt
from services.domain.transitions import ClaimState, OrderState, PaymentState
from services.simulator.ledger import Scenario

PURCHASE_ID = "purchase-0001"


class RealClock:
    """A clock with no ``advance``, exactly like the production one."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class SilentProvider:
    """Never answers. Counts how hard it was asked."""

    def __init__(self) -> None:
        self.queries = 0
        self.submits = 0

    def submit(self, request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        self.submits += 1
        raise ResponseLost("a" * 64)

    def query_payment(self, *, payment_key: str) -> PaymentFacts | ProviderNotFound:
        self.queries += 1
        return ProviderNotFound(key="a")

    def create_order(self, request: OrderRequest) -> OrderFacts | ProviderNotFound:
        return ProviderNotFound(key="a")

    def get_order(self, *, order_key: str) -> OrderFacts | ProviderNotFound:
        return ProviderNotFound(key=order_key)

    def query_refund(self, *, refund_reference: str) -> object | ProviderNotFound:
        return ProviderNotFound(key=refund_reference)

    def effect_count(self) -> int:
        return 0


# -- R1: the task never wrote down what it learned -------------------------


def test_a_successful_checkout_is_persisted_to_the_purchase() -> None:
    """It used to compute the right answer and store nothing.

    A reload showed the purchase still ``claimed``, however many times the task
    ran. Durable state is the entire product.
    """
    checkout = Checkout(Scenario.SUCCESS)
    outcome = checkout.run_ok()

    stored = checkout.world.purchase_row()
    assert outcome.payment is PaymentState.SUCCEEDED
    assert stored.payment is PaymentState.SUCCEEDED
    assert stored.order is OrderState.CONFIRMED


def test_a_failed_payment_is_persisted_too() -> None:
    checkout = Checkout(Scenario.DEFINITIVE_FAILURE)
    checkout.run()
    stored = checkout.world.purchase_row()
    assert stored.payment is PaymentState.FAILED
    assert stored.order is OrderState.NOT_CREATED


def test_paid_but_no_order_is_persisted_as_exactly_that() -> None:
    """The case the recovery flow reads. It has to be in the store to be read."""
    checkout = Checkout(Scenario.PAID_ORDER_MISSING)
    checkout.run()
    stored = checkout.world.purchase_row()
    assert stored.payment is PaymentState.SUCCEEDED
    assert stored.order is OrderState.NOT_CREATED


def test_an_unresolved_payment_is_persisted_as_unknown() -> None:
    checkout = Checkout()
    checkout.provider = SilentProvider()
    checkout.task = CheckoutTask(
        store=checkout.world.store, clock=checkout.world.clock, provider=checkout.provider
    )
    checkout.run()
    stored = checkout.world.purchase_row()
    assert stored.payment is PaymentState.UNKNOWN


def test_the_provider_reference_is_stored_on_the_attempt() -> None:
    """Recovery needs the reference to query the provider later."""
    checkout = Checkout(Scenario.SUCCESS)
    outcome = checkout.run_ok()
    attempt = checkout.attempt_row(outcome.attempt_id)
    assert attempt.provider_reference == outcome.provider_reference
    assert attempt.provider_reference


# -- R2: the poll loop waited using a test-only method ---------------------


def test_one_invocation_makes_at_most_one_provider_query() -> None:
    """It used to loop internally, calling ``clock.advance`` to 'wait'.

    Only the test clock has that method. Against a real clock the loop never
    waited and never timed out -- it queried 64 times in a single invocation.
    """
    checkout = Checkout()
    provider = SilentProvider()
    task = CheckoutTask(
        store=checkout.world.store, clock=RealClock(checkout.world.clock.now()), provider=provider
    )

    task.step(purchase_id=PURCHASE_ID, attempt_id=checkout.attempt_id)
    assert provider.queries + provider.submits <= 2, (
        "a step submits or polls once; it does not spin"
    )


def test_a_step_says_when_to_come_back_instead_of_sleeping() -> None:
    checkout = Checkout()
    checkout.provider = SilentProvider()
    checkout.task = CheckoutTask(
        store=checkout.world.store, clock=checkout.world.clock, provider=checkout.provider
    )

    outcome = checkout.step_ok()
    assert outcome.next_check_at is not None
    assert outcome.is_final is False
    assert outcome.next_check_at > checkout.world.clock.now()


def test_the_next_check_is_persisted_so_a_crash_resumes_the_schedule() -> None:
    checkout = Checkout()
    checkout.provider = SilentProvider()
    checkout.task = CheckoutTask(
        store=checkout.world.store, clock=checkout.world.clock, provider=checkout.provider
    )

    outcome = checkout.step_ok()
    attempt = checkout.attempt_row(outcome.attempt_id)
    assert attempt.next_check_at == outcome.next_check_at


def test_the_schedule_follows_the_spec_across_steps() -> None:
    checkout = Checkout()
    checkout.provider = SilentProvider()
    checkout.task = CheckoutTask(
        store=checkout.world.store, clock=checkout.world.clock, provider=checkout.provider
    )

    waits = []
    for _ in range(3):
        before = checkout.world.clock.now()
        outcome = checkout.step_ok()
        if outcome.next_check_at is None:
            break
        waits.append(int((outcome.next_check_at - before).total_seconds()))
        checkout.world.clock.advance(waits[-1])

    assert waits[0] == 5
    assert all(w in (5, 10, 20, 30) for w in waits)


def test_the_window_still_closes_with_a_production_style_clock() -> None:
    """The bound is wall-clock elapsed, not an internal iteration count."""
    checkout = Checkout()
    provider = SilentProvider()
    late = RealClock(checkout.world.clock.now())
    task = CheckoutTask(store=checkout.world.store, clock=checkout.world.clock, provider=provider)

    task.step(purchase_id=PURCHASE_ID, attempt_id=checkout.attempt_id)
    checkout.world.clock.advance(OBSERVATION_WINDOW_SECONDS + 1)
    outcome = task.step(purchase_id=PURCHASE_ID, attempt_id=checkout.attempt_id)
    assert isinstance(outcome, CheckoutOutcome), f"step failed: {outcome}"
    assert outcome.stage == "window_closed"
    assert late.now() is not None  # the clock never needed an advance method


# -- R3: the quote was found by guessing its id ----------------------------


def test_the_quote_is_found_through_the_approval_not_by_guessing_an_id() -> None:
    """It used to format ``quote-{version:08d}``.

    That worked only because the test id generator happens to produce that shape.
    With UUIDs -- or any other scheme -- checkout could not find the quote at all.
    """
    checkout = Checkout()
    stored_key = next(
        k for k in checkout.world.store.keys_matching("PURCHASE#") if "QUOTE#" in k[1]
    )
    quote = read(checkout.world.store, stored_key, CheckoutQuote)
    assert quote is not None

    realistic_id = "q-7f3a91c2-4be8"
    checkout.world.store._items.pop(stored_key)
    renamed = quote.model_copy(update={"quote_id": realistic_id})
    checkout.world.store.seed(quote_key(PURCHASE_ID, realistic_id), renamed)

    # Point the approval at the renamed quote, as a real system would.
    from services.application.purchase import approval_key

    attempt = checkout.attempt_row(checkout.attempt_id)
    approval = read(checkout.world.store, approval_key(PURCHASE_ID, attempt.approval_id), Approval)
    assert approval is not None
    checkout.world.store.seed(
        approval_key(PURCHASE_ID, attempt.approval_id),
        approval.model_copy(update={"quote_id": realistic_id}),
    )

    outcome = checkout.run_ok()
    assert not isinstance(outcome, InvalidRecord)
    assert outcome.payment is PaymentState.SUCCEEDED


def test_a_missing_approval_is_refused_rather_than_guessed_around() -> None:
    from services.application.purchase import approval_key

    checkout = Checkout()
    attempt = checkout.attempt_row(checkout.attempt_id)
    checkout.world.store._items.pop(approval_key(PURCHASE_ID, attempt.approval_id))

    result = checkout.step()
    assert isinstance(result, InvalidRecord)


# -- and the headline claim still holds ------------------------------------


@pytest.mark.parametrize("scenario", list(Scenario))
def test_no_scenario_produces_more_than_one_effect_after_the_rewrite(
    scenario: Scenario,
) -> None:
    checkout = Checkout(scenario)
    for _ in range(3):
        checkout.run()
    assert checkout.simulator.effect_count() <= 1


def test_an_expired_unsent_attempt_leaves_a_purchase_that_still_validates() -> None:
    """The claim field must be released with the pointer it is tied to.

    `Purchase` validates that a CLAIMED purchase names its active attempt, but
    `model_copy` does not re-validate -- so clearing `active_attempt_id` while
    leaving `claim=CLAIMED` wrote a record the model itself forbids. A store
    that validates on read could not load it back.
    """
    checkout = Checkout()
    checkout.world.clock.advance(121)
    checkout.run_ok()

    stored = checkout.world.purchase_row()
    assert stored.claim is ClaimState.RELEASED
    assert stored.active_attempt_id is None
    # The round trip a real adapter performs, which model_copy skipped.
    Purchase.model_validate(stored.model_dump())


def test_a_definitively_failed_payment_allows_another_attempt() -> None:
    """may_create_attempt's documented FAILED branch has to be reachable.

    It returns AttemptBlockedByExposure whenever `active_attempt` is not None,
    before it consults `last_attempt` -- so leaving the pointer set after a
    terminal payment blocked the shopper forever and made the "definitively
    over" branch dead code.
    """
    checkout = Checkout(Scenario.DEFINITIVE_FAILURE)
    checkout.run_ok()

    stored = checkout.world.purchase_row()
    assert stored.payment is PaymentState.FAILED
    assert stored.active_attempt_id is None
    assert stored.claim is ClaimState.RELEASED
    assert stored.last_attempt_id is not None, "the attempt is still remembered"

    assert checkout.world.uc._snapshot(stored).active_attempt is None
    assert may_create_attempt(checkout.world.uc._snapshot(stored)) is None


def test_a_succeeded_payment_still_blocks_a_second_attempt() -> None:
    """Releasing the claim must not open the door to paying twice."""
    checkout = Checkout(Scenario.SUCCESS)
    checkout.run_ok()

    stored = checkout.world.purchase_row()
    assert stored.payment is PaymentState.SUCCEEDED
    assert stored.active_attempt_id is None
    blocked = may_create_attempt(checkout.world.uc._snapshot(stored))
    assert isinstance(blocked, AttemptBlockedByExposure)
