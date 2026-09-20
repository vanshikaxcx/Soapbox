"""Case creation and callback ingestion (WP-09, closing the last gaps).

The checkout task used to return ``case_opened=True`` and store nothing, and the
callback contract existed without anything that ran it end to end. Both are real
now, and these are the tests that would have caught either being decoration.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from services.application.callbacks import (
    CallbackBody,
    CallbackHeaders,
    Disposition,
    FactKind,
    Rejection,
    _timestamp_text,
    sign,
)
from services.application.cases import (
    CallbackIngest,
    CaseService,
    case_key,
    inbox_key,
    missing_facts_for,
)
from services.application.checkout import CheckoutTask
from services.application.checkout_test import Checkout
from services.application.fakes import SequentialIds
from services.application.ports import Key, StateStore, read
from services.domain.evidence import Case, InboxEvent, MissingFact
from services.domain.transitions import InboxState, OrderState, PaymentState
from services.simulator.ledger import Scenario

PURCHASE_ID = "purchase-0001"
SECRET = b"a-rotated-secret-from-secrets-manager"


def a_case_service(checkout: Checkout) -> CaseService:
    return CaseService(store=checkout.world.store, clock=checkout.world.clock, ids=SequentialIds())


# -- the case is actually written ------------------------------------------


def test_paid_with_no_order_writes_a_real_case() -> None:
    checkout = Checkout(Scenario.PAID_ORDER_MISSING)
    checkout.task = CheckoutTask(
        store=checkout.world.store,
        clock=checkout.world.clock,
        provider=checkout.provider,
        cases=a_case_service(checkout),
    )
    outcome = checkout.run_ok()
    assert outcome.case_opened is True

    stored = must_read(checkout.world.store, case_key(PURCHASE_ID), Case)
    assert isinstance(stored, Case), "the flag used to be all there was"
    assert MissingFact.ORDER_EXISTENCE in stored.missing_facts


def test_the_case_names_what_is_missing_rather_than_leaving_it_blank() -> None:
    checkout = Checkout(Scenario.PAID_ORDER_MISSING)
    checkout.task = CheckoutTask(
        store=checkout.world.store,
        clock=checkout.world.clock,
        provider=checkout.provider,
        cases=a_case_service(checkout),
    )
    checkout.run()
    case = must_read(checkout.world.store, case_key(PURCHASE_ID), Case)
    assert case.missing_facts
    assert case.has_gaps is True


def test_opening_a_case_twice_refreshes_rather_than_duplicating() -> None:
    checkout = Checkout(Scenario.PAID_ORDER_MISSING)
    cases = a_case_service(checkout)
    checkout.task = CheckoutTask(
        store=checkout.world.store,
        clock=checkout.world.clock,
        provider=checkout.provider,
        cases=cases,
    )
    checkout.run()
    first = must_read(checkout.world.store, case_key(PURCHASE_ID), Case)
    cases.open_case(purchase_id=PURCHASE_ID)
    second = must_read(checkout.world.store, case_key(PURCHASE_ID), Case)
    assert second.case_id == first.case_id
    assert second.version == first.version + 1


def test_a_resolved_purchase_has_nothing_missing() -> None:
    checkout = Checkout(Scenario.SUCCESS)
    checkout.run()
    purchase = checkout.world.purchase_row()
    assert purchase.payment is PaymentState.SUCCEEDED
    assert purchase.order is OrderState.CONFIRMED
    assert missing_facts_for(purchase) == ()


def test_an_unknown_payment_lists_the_payment_outcome_as_missing() -> None:
    checkout = Checkout()
    purchase = checkout.world.purchase_row()
    unresolved = purchase.model_copy(update={"payment": PaymentState.UNKNOWN})
    assert MissingFact.PAYMENT_OUTCOME in missing_facts_for(unresolved)


def test_reading_a_case_belonging_to_someone_else_is_refused() -> None:
    from services.application.purchase import NotFound

    checkout = Checkout(Scenario.PAID_ORDER_MISSING)
    cases = a_case_service(checkout)
    checkout.task = CheckoutTask(
        store=checkout.world.store,
        clock=checkout.world.clock,
        provider=checkout.provider,
        cases=cases,
    )
    checkout.run()
    assert isinstance(cases.read_case(owner_id="owner-9999", purchase_id=PURCHASE_ID), NotFound)


# -- callbacks, end to end -------------------------------------------------


def an_ingest(checkout: Checkout) -> CallbackIngest:
    return CallbackIngest(
        store=checkout.world.store, clock=checkout.world.clock, ids=SequentialIds(), secret=SECRET
    )


def must_read[T](store: StateStore, key: Key, kind: type[T]) -> T:
    """Read a row the test requires to exist, typed.

    store.get returns `object | None`, so reaching through it loses every type.
    Asserting here makes a missing row say so plainly instead of surfacing as an
    AttributeError on the next line.
    """
    found = read(store, key, kind)
    assert found is not None, f"expected a row at {key}"
    return found


def a_delivery(
    checkout: Checkout,
    *,
    status: str = "succeeded",
    amount: int | None = None,
    event_id: str = "evt-0001",
    at: datetime | None = None,
) -> tuple[CallbackHeaders, bytes, CallbackBody]:
    attempt = checkout.attempt_row(checkout.attempt_id)
    moment = at or checkout.world.clock.now()
    raw = (
        b'{"event_id":"'
        + event_id.encode()
        + b'","key":"'
        + attempt.payment_key.encode()
        + b'","status":"'
        + status.encode()
        + b'"}'
    )
    headers = CallbackHeaders(
        provider="sim",
        event_id=event_id,
        delivery_timestamp=moment,
        signature=sign(
            secret=SECRET,
            delivery_timestamp=_timestamp_text(moment),
            event_id=event_id,
            raw_body=raw,
        ),
    )
    body = CallbackBody(
        event_id=event_id,
        provider="sim",
        kind=FactKind.PAYMENT,
        key=attempt.payment_key,
        status=status,
        amount_paise=amount if amount is not None else checkout.quote.total.amount_paise,
        seller_id=checkout.quote.demo_seller_id,
        observed_at=moment,
    )
    return headers, raw, body


def test_a_valid_callback_applies_the_payment_and_is_recorded() -> None:
    checkout = Checkout()
    headers, raw, body = a_delivery(checkout)
    result = an_ingest(checkout).ingest(headers=headers, raw_body=raw, body=body)

    assert result.accepted is True
    assert result.disposition is Disposition.APPLIED
    assert result.applied_payment is PaymentState.SUCCEEDED

    stored = checkout.world.purchase_row()
    assert stored.payment is PaymentState.SUCCEEDED


def test_the_inbox_row_is_written_for_every_accepted_delivery() -> None:
    """Durability precedes acknowledgement."""
    checkout = Checkout()
    headers, raw, body = a_delivery(checkout)
    an_ingest(checkout).ingest(headers=headers, raw_body=raw, body=body)
    event = must_read(checkout.world.store, inbox_key("sim", "evt-0001"), InboxEvent)
    assert isinstance(event, InboxEvent)
    assert event.status is InboxState.APPLIED


def test_a_redelivery_of_the_same_bytes_changes_nothing() -> None:
    checkout = Checkout()
    headers, raw, body = a_delivery(checkout)
    ingest = an_ingest(checkout)
    ingest.ingest(headers=headers, raw_body=raw, body=body)
    before = checkout.world.purchase_row().version

    again = ingest.ingest(headers=headers, raw_body=raw, body=body)
    assert again.disposition is Disposition.DUPLICATE
    assert checkout.world.purchase_row().version == before


def test_the_same_event_id_with_a_different_body_is_never_applied() -> None:
    checkout = Checkout()
    ingest = an_ingest(checkout)
    first_headers, first_raw, first_body = a_delivery(checkout)
    ingest.ingest(headers=first_headers, raw_body=first_raw, body=first_body)

    headers, raw, body = a_delivery(checkout, status="failed")
    result = ingest.ingest(headers=headers, raw_body=raw, body=body)
    assert result.disposition is Disposition.CONFLICTED
    assert checkout.world.purchase_row().payment is (PaymentState.SUCCEEDED)


def test_a_callback_claiming_a_different_amount_is_quarantined() -> None:
    checkout = Checkout()
    headers, raw, body = a_delivery(checkout, amount=1)
    result = an_ingest(checkout).ingest(headers=headers, raw_body=raw, body=body)
    assert result.disposition is Disposition.QUARANTINED
    assert checkout.world.purchase_row().payment is not (PaymentState.SUCCEEDED)


def test_an_unsigned_delivery_touches_nothing_at_all() -> None:
    checkout = Checkout()
    headers, raw, body = a_delivery(checkout)
    tampered = headers.model_copy(update={"signature": "f" * 64})
    result = an_ingest(checkout).ingest(headers=tampered, raw_body=raw, body=body)

    assert result.accepted is False
    assert result.rejection is Rejection.BAD_SIGNATURE
    assert read(checkout.world.store, inbox_key("sim", "evt-0001"), InboxEvent) is None


def test_a_delivery_outside_the_skew_window_touches_nothing() -> None:
    checkout = Checkout()
    late = checkout.world.clock.now() + timedelta(seconds=400)
    headers, raw, body = a_delivery(checkout, at=late)
    result = an_ingest(checkout).ingest(headers=headers, raw_body=raw, body=body)
    assert result.rejection is Rejection.SKEW_TOO_LARGE
    assert read(checkout.world.store, inbox_key("sim", "evt-0001"), InboxEvent) is None


def test_a_late_success_callback_opens_the_case_when_no_order_exists() -> None:
    checkout = Checkout()
    headers, raw, body = a_delivery(checkout)
    result = an_ingest(checkout).ingest(headers=headers, raw_body=raw, body=body)
    assert result.case_opened is True
    assert isinstance(must_read(checkout.world.store, case_key(PURCHASE_ID), Case), Case)


def test_an_old_pending_cannot_downgrade_a_succeeded_payment() -> None:
    """WP-02's rule, reaching all the way through the callback path."""
    checkout = Checkout()
    ingest = an_ingest(checkout)
    headers, raw, body = a_delivery(checkout)
    ingest.ingest(headers=headers, raw_body=raw, body=body)

    headers, raw, body = a_delivery(checkout, status="pending", event_id="evt-0002")
    result = ingest.ingest(headers=headers, raw_body=raw, body=body)

    assert result.disposition is Disposition.QUARANTINED
    assert checkout.world.purchase_row().payment is (PaymentState.SUCCEEDED)
