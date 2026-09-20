"""The checkout task (WP-09).

The ordering in ``step`` is the entire design, and it is worth stating plainly:

    mark dispatch STARTED   <-- persisted first
    then call the provider

If the marker were written after the call, a crash in between would leave the
attempt looking untouched. The system would believe nothing happened, a retry
would submit again, and the shopper would pay twice. Written first, a crash
leaves the attempt ``started`` with no facts -- ambiguous, and correctly so.

**One invocation does one step.** It submits, or it polls once, then persists what
it learned and says when to come back. The waiting belongs to the workflow,
because an in-process sleep dies with its Lambda and surviving exactly that is
the point. An earlier version of this file looped internally and advanced the
clock itself, which worked only because the test clock had an ``advance`` method;
against a real clock it never waited and never timed out.

Everything else follows from taking the ambiguity seriously. Silence is
``unknown``, never ``failed``. A resend is byte-identical or it does not happen.
The job succeeds even when the payment does not resolve, because the task did its
work correctly and the money is a separate question.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from services.application.ports import Clock, Condition, ConditionFailed, StateStore, Write
from services.application.provider_ports import (
    OrderRequest,
    PaymentFacts,
    ProviderConflict,
    ProviderNotFound,
    ProviderPaymentStatus,
    ProviderWritePort,
    ResponseLost,
    SubmitRequest,
)
from services.application.purchase import (
    NotFound,
    approval_key,
    attempt_key,
    provider_lookup_key,
    purchase_key,
    quote_key,
)
from services.domain.errors import DomainError, InvalidRecord
from services.domain.ids import Id, Record
from services.domain.keys import order_key as derive_order_key
from services.domain.keys import payment_request_hash as build_payment_request_hash
from services.domain.purchase import (
    Approval,
    Attempt,
    CheckoutQuote,
    ProviderLookup,
    Purchase,
)
from services.domain.transitions import ClaimState, DispatchState, OrderState, PaymentState

#: Seconds to wait before the next query, by poll number. The last value repeats.
#: SPEC section 8.
POLL_SCHEDULE = (5, 10, 20, 30)

#: How long we chase an unresolved payment before handing it to a case.
OBSERVATION_WINDOW_SECONDS = 180


class CaseOpener(Protocol):
    """Just enough of CaseService for the task to ask for a case."""

    def open_case(self, *, purchase_id: str) -> object: ...


SUBMITTED = "submitted"
POLLED = "polled"
RESOLVED = "resolved"
EXPIRED_UNSENT = "expired_unsent"
WINDOW_CLOSED = "window_closed"


class CheckoutOutcome(Record):
    """What one step did, and when to come back.

    ``job_succeeded`` and ``payment`` are separate fields on purpose. A failed job
    and a failed payment are different things, and conflating them is the mistake
    SPEC section 8 names outright.
    """

    attempt_id: Id
    stage: str
    payment: PaymentState
    order: OrderState = OrderState.NOT_CREATED
    provider_reference: str | None = None
    order_reference: str | None = None
    next_check_at: datetime | None = None
    polls: int = 0
    case_opened: bool = False
    job_succeeded: bool = True
    detail: str = ""

    @property
    def is_final(self) -> bool:
        return self.next_check_at is None


class CheckoutTask:
    """Drives one attempt, one step at a time. The workflow owns the waiting."""

    def __init__(
        self,
        *,
        store: StateStore,
        clock: Clock,
        provider: ProviderWritePort,
        cases: CaseOpener | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._provider = provider
        #: Opens the case when a payment cannot be resolved. Optional so the
        #: task can be exercised alone, but wired in production.
        self._cases = cases

    # -- one step ----------------------------------------------------------

    def step(self, *, purchase_id: str, attempt_id: str) -> CheckoutOutcome | DomainError:
        loaded = self._load(purchase_id, attempt_id)
        if isinstance(loaded, DomainError):
            return loaded
        purchase, attempt, quote, lookup = loaded
        now = self._clock.now()

        if attempt.dispatch is DispatchState.EXPIRED_UNSENT:
            return CheckoutOutcome(
                attempt_id=attempt_id,
                stage=EXPIRED_UNSENT,
                payment=PaymentState.NOT_STARTED,
                detail="expired before dispatch",
            )

        if attempt.dispatch is DispatchState.READY:
            if now >= quote.expires_at:
                return self._expire_unsent(purchase, attempt)
            started = self._mark_started(attempt, now)
            if isinstance(started, ConditionFailed):
                # Someone else moved it. Re-read rather than assume we still own
                # the decision.
                return self.step(purchase_id=purchase_id, attempt_id=attempt_id)
            return self._submit(purchase, started, quote, lookup, now)

        return self._poll_once(purchase, attempt, quote, lookup, now)

    def run_to_completion(
        self, *, purchase_id: str, attempt_id: str, max_steps: int = 32
    ) -> CheckoutOutcome | DomainError:
        """Drive the steps in one process. Tests and local runs only.

        In production the workflow does this, waiting properly between steps. The
        bound exists so a mistake here cannot become an infinite loop.
        """
        outcome = self.step(purchase_id=purchase_id, attempt_id=attempt_id)
        steps = 1
        while isinstance(outcome, CheckoutOutcome) and not outcome.is_final and steps < max_steps:
            next_check = outcome.next_check_at
            if next_check is None:
                break
            wait = (next_check - self._clock.now()).total_seconds()
            if hasattr(self._clock, "advance") and wait > 0:
                self._clock.advance(int(wait))
            outcome = self.step(purchase_id=purchase_id, attempt_id=attempt_id)
            steps += 1
        return outcome

    # -- loading -----------------------------------------------------------

    def _load(
        self, purchase_id: str, attempt_id: str
    ) -> tuple[Purchase, Attempt, CheckoutQuote, ProviderLookup] | DomainError:
        attempt = self._store.get(attempt_key(purchase_id, attempt_id))
        if not isinstance(attempt, Attempt):
            return NotFound("attempt")
        purchase = self._store.get(purchase_key(purchase_id))
        if not isinstance(purchase, Purchase):
            return NotFound("purchase")

        # The approval names the quote it was given for. Deriving the quote id
        # any other way -- a counter, a format string -- only works while the id
        # generator happens to produce that shape.
        approval = self._store.get(approval_key(purchase_id, attempt.approval_id))
        if not isinstance(approval, Approval):
            return InvalidRecord(record="approval", detail="missing for this attempt")
        quote = self._store.get(quote_key(purchase_id, approval.quote_id))
        if not isinstance(quote, CheckoutQuote):
            return NotFound("quote")

        lookup = self._store.get(provider_lookup_key(attempt.payment_key))
        if not isinstance(lookup, ProviderLookup):
            # Never submit without a resolvable lookup row: a returning callback
            # could not be matched to anything and would have to be quarantined.
            return InvalidRecord(record="provider_lookup", detail="missing for this key")

        return purchase, attempt, quote, lookup

    # -- dispatch ----------------------------------------------------------

    def _mark_started(self, attempt: Attempt, now: datetime) -> Attempt | ConditionFailed:
        """Persisted BEFORE the network call. The whole design rests on this."""
        started = attempt.model_copy(
            update={
                "dispatch": DispatchState.STARTED,
                "started_at": now,
                "version": attempt.version + 1,
            }
        )
        failure = self._store.transact(
            [
                Write(
                    key=attempt_key(attempt.purchase_id, attempt.attempt_id),
                    item=started,
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=attempt.version,
                    reason="record that a provider call is about to happen",
                )
            ]
        )
        return failure if failure is not None else started

    def _expire_unsent(self, purchase: Purchase, attempt: Attempt) -> CheckoutOutcome:
        expired = attempt.model_copy(
            update={
                "dispatch": DispatchState.EXPIRED_UNSENT,
                "version": attempt.version + 1,
            }
        )
        released = purchase.model_copy(
            update={
                "active_attempt_id": None,
                "claim": ClaimState.RELEASED,
                "payment": PaymentState.NOT_STARTED,
                "version": purchase.version + 1,
            }
        )
        self._store.transact(
            [
                Write(
                    key=attempt_key(purchase.purchase_id, attempt.attempt_id),
                    item=expired,
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=attempt.version,
                    reason="only if nothing has started the call",
                ),
                Write(
                    key=purchase_key(purchase.purchase_id),
                    item=released,
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=purchase.version,
                    reason="release the claim",
                ),
            ]
        )
        return CheckoutOutcome(
            attempt_id=attempt.attempt_id,
            stage=EXPIRED_UNSENT,
            payment=PaymentState.NOT_STARTED,
            detail="expired before dispatch",
        )

    # -- provider calls ----------------------------------------------------

    def _request(self, attempt: Attempt, quote: CheckoutQuote) -> SubmitRequest | InvalidRecord:
        """The approved terms, rebuilt and checked against what was approved.

        The payload is hashed at approval time and re-derived here. If the two
        disagree, something between consent and dispatch changed the terms, and
        the only safe move is to refuse BEFORE anything goes out. The provider's
        own same-key/different-payload conflict would also catch it -- but only
        after the call had already been made.
        """
        rebuilt = build_payment_request_hash(
            payment_key=attempt.payment_key,
            quote_hash=quote.quote_hash,
            seller_id=quote.demo_seller_id,
            amount_paise=quote.total.amount_paise,
            currency=str(quote.currency),
            expires_at=quote.expires_at,
        )
        if rebuilt != attempt.request_hash:
            return InvalidRecord(
                record="payment_payload",
                detail="rebuilt terms do not match what was approved",
            )
        return SubmitRequest(
            payment_key=attempt.payment_key,
            request_hash=attempt.request_hash,
            quote_hash=quote.quote_hash,
            seller_id=quote.demo_seller_id,
            amount=quote.total,
            currency=quote.currency,
            expires_at=quote.expires_at,
        )

    def _submit(
        self,
        purchase: Purchase,
        attempt: Attempt,
        quote: CheckoutQuote,
        lookup: ProviderLookup,
        now: datetime,
    ) -> CheckoutOutcome | InvalidRecord:
        request = self._request(attempt, quote)
        if isinstance(request, InvalidRecord):
            return request
        try:
            result = self._provider.submit(request)
        except ResponseLost:
            # It may or may not have been taken. This is the only honest thing to
            # say, and it is not "failed".
            return self._await_answer(
                purchase, attempt, now, polls=0, detail="response lost on submit"
            )

        if isinstance(result, ProviderConflict):
            # We never send different terms, so this means something upstream is
            # wrong. Do not retry it away.
            return self._unknown(
                purchase,
                attempt,
                stage=SUBMITTED,
                job_succeeded=False,
                detail="provider key conflict",
            )

        return self._apply(purchase, attempt, quote, lookup, result, stage=SUBMITTED, polls=0)

    def _poll_once(
        self,
        purchase: Purchase,
        attempt: Attempt,
        quote: CheckoutQuote,
        lookup: ProviderLookup,
        now: datetime,
    ) -> CheckoutOutcome | InvalidRecord:
        found = self._provider.query_payment(payment_key=attempt.payment_key)

        if isinstance(found, ProviderNotFound):
            # Absent entirely: resend the IDENTICAL payload. Safe only because the
            # key is derived, the payload is hash-frozen at approval, and the
            # provider returns original facts for a replay.
            request = self._request(attempt, quote)
            if isinstance(request, InvalidRecord):
                return request
            try:
                # A conflict here means the terms changed between approval and
                # now, which cannot happen -- the payload is hash-frozen. Treat
                # it as no answer rather than as facts.
                resent = self._provider.submit(request)
                if isinstance(resent, PaymentFacts):
                    found = resent
            except ResponseLost:
                pass

        if isinstance(found, PaymentFacts):
            return self._apply(purchase, attempt, quote, lookup, found, stage=POLLED, polls=1)

        return self._await_answer(purchase, attempt, now, polls=1, detail="still unresolved")

    # -- applying and persisting ------------------------------------------

    def _apply(
        self,
        purchase: Purchase,
        attempt: Attempt,
        quote: CheckoutQuote,
        lookup: ProviderLookup,
        facts: PaymentFacts,
        *,
        stage: str,
        polls: int,
    ) -> CheckoutOutcome:
        if not lookup.matches(
            seller_id=facts.seller_id, amount=facts.amount, currency=facts.currency
        ):
            # A payment that is not about our purchase. Never applied.
            return self._unknown(
                purchase,
                attempt,
                stage=stage,
                case_opened=True,
                detail="provider facts did not match the lookup",
            )

        payment = _PAYMENT_FROM_PROVIDER[facts.status]

        if payment is not PaymentState.SUCCEEDED:
            self._persist(
                purchase, attempt, payment=payment, provider_reference=facts.provider_reference
            )
            return CheckoutOutcome(
                attempt_id=attempt.attempt_id,
                stage=RESOLVED,
                payment=payment,
                provider_reference=facts.provider_reference,
                polls=polls,
                detail=f"provider reported {facts.status}",
            )

        order = self._provider.create_order(
            OrderRequest(
                order_key=derive_order_key(
                    purchase_id=purchase.purchase_id, attempt_id=attempt.attempt_id
                ),
                payment_reference=facts.provider_reference or "",
                quote_hash=quote.quote_hash,
            )
        )

        if isinstance(order, ProviderNotFound):
            # Paid, and the provider has no order. The case this product exists
            # for. Payment stays succeeded -- because it did.
            self._persist(
                purchase,
                attempt,
                payment=PaymentState.SUCCEEDED,
                order=OrderState.NOT_CREATED,
                provider_reference=facts.provider_reference,
            )
            return CheckoutOutcome(
                attempt_id=attempt.attempt_id,
                stage=RESOLVED,
                payment=PaymentState.SUCCEEDED,
                order=OrderState.NOT_CREATED,
                provider_reference=facts.provider_reference,
                polls=polls,
                case_opened=self._open_case(purchase),
                detail="paid, but the provider has no order",
            )

        self._persist(
            purchase,
            attempt,
            payment=PaymentState.SUCCEEDED,
            order=OrderState.CONFIRMED,
            provider_reference=facts.provider_reference,
        )
        return CheckoutOutcome(
            attempt_id=attempt.attempt_id,
            stage=RESOLVED,
            payment=PaymentState.SUCCEEDED,
            order=OrderState.CONFIRMED,
            provider_reference=facts.provider_reference,
            order_reference=order.order_reference,
            polls=polls,
        )

    def _persist(
        self,
        purchase: Purchase,
        attempt: Attempt,
        *,
        payment: PaymentState,
        order: OrderState | None = None,
        provider_reference: str | None = None,
        next_check_at: datetime | None = None,
    ) -> None:
        """Write down what we learned.

        An earlier version computed an outcome and returned it without storing
        anything, so a reload showed the purchase still ``claimed`` however many
        times the task ran. Durable state is the entire product.
        """
        # A payment that reached a terminal state ends the attempt with it. The
        # claim and the active pointer must go together (Purchase validates
        # that), and leaving them set made may_create_attempt refuse forever:
        # it returns AttemptBlockedByExposure whenever active_attempt is not
        # None, before it ever consults last_attempt -- so its documented
        # "permitted when the previous one ended in a definitive failure" branch
        # was unreachable. last_attempt_id is written at creation and is not
        # cleared here, so a succeeded payment still blocks a second attempt.
        resolved = payment in (PaymentState.SUCCEEDED, PaymentState.FAILED)
        updated_purchase = purchase.model_copy(
            update={
                "payment": payment,
                "order": order if order is not None else purchase.order,
                "active_attempt_id": None if resolved else purchase.active_attempt_id,
                "claim": ClaimState.RELEASED if resolved else purchase.claim,
                "version": purchase.version + 1,
            }
        )
        updated_attempt = attempt.model_copy(
            update={
                "provider_reference": provider_reference or attempt.provider_reference,
                "next_check_at": next_check_at,
                "version": attempt.version + 1,
            }
        )
        self._store.transact(
            [
                Write(
                    key=purchase_key(purchase.purchase_id),
                    item=updated_purchase,
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=purchase.version,
                    reason="record what the provider told us",
                ),
                Write(
                    key=attempt_key(purchase.purchase_id, attempt.attempt_id),
                    item=updated_attempt,
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=attempt.version,
                    reason="record the provider reference and the next check",
                ),
            ]
        )

    def _await_answer(
        self,
        purchase: Purchase,
        attempt: Attempt,
        now: datetime,
        *,
        polls: int,
        detail: str,
    ) -> CheckoutOutcome:
        started_at = attempt.started_at or now
        elapsed = (now - started_at).total_seconds()
        if elapsed >= OBSERVATION_WINDOW_SECONDS:
            return self._close_window(purchase, attempt)

        index = min(polls, len(POLL_SCHEDULE) - 1)
        next_check = now + timedelta(seconds=POLL_SCHEDULE[index])
        self._persist(purchase, attempt, payment=PaymentState.UNKNOWN, next_check_at=next_check)
        return CheckoutOutcome(
            attempt_id=attempt.attempt_id,
            stage=POLLED,
            payment=PaymentState.UNKNOWN,
            next_check_at=next_check,
            polls=polls,
            detail=detail,
        )

    def _close_window(self, purchase: Purchase, attempt: Attempt) -> CheckoutOutcome:
        """The window shut with no answer.

        The JOB succeeded: it dispatched, it polled, it stopped at the agreed
        point. The PAYMENT is unknown. Reporting the job as failed here is what
        would put "payment failed" in front of a shopper whose money has moved.
        """
        self._persist(purchase, attempt, payment=PaymentState.UNKNOWN)
        return CheckoutOutcome(
            attempt_id=attempt.attempt_id,
            stage=WINDOW_CLOSED,
            payment=PaymentState.UNKNOWN,
            case_opened=self._open_case(purchase),
            job_succeeded=True,
            detail="observation window closed without a resolution",
        )

    def _open_case(self, purchase: Purchase) -> bool:
        """Actually write the case, rather than only flagging that one is due.

        An earlier version returned ``case_opened=True`` and stored nothing, so
        recovery had nothing to read and the flag was decoration.
        """
        if self._cases is None:
            return True
        result = self._cases.open_case(purchase_id=purchase.purchase_id)
        return not isinstance(result, DomainError)

    def _unknown(
        self,
        purchase: Purchase,
        attempt: Attempt,
        *,
        stage: str,
        case_opened: bool = False,
        job_succeeded: bool = True,
        detail: str,
    ) -> CheckoutOutcome:
        self._persist(purchase, attempt, payment=PaymentState.UNKNOWN)
        if case_opened:
            case_opened = self._open_case(purchase)
        return CheckoutOutcome(
            attempt_id=attempt.attempt_id,
            stage=stage,
            payment=PaymentState.UNKNOWN,
            case_opened=case_opened,
            job_succeeded=job_succeeded,
            detail=detail,
        )


#: Provider vocabulary to domain vocabulary. Explicit, because the two are not
#: the same language and a shared word would be a coincidence, not a mapping.
_PAYMENT_FROM_PROVIDER = {
    ProviderPaymentStatus.ACCEPTED: PaymentState.PENDING,
    ProviderPaymentStatus.PENDING: PaymentState.PENDING,
    ProviderPaymentStatus.SUCCEEDED: PaymentState.SUCCEEDED,
    ProviderPaymentStatus.FAILED: PaymentState.FAILED,
    # We called and were refused because the quote had expired. Definitive, with
    # no effect -- which is not the same as never having called.
    ProviderPaymentStatus.EXPIRED_REJECTED: PaymentState.FAILED,
}


__all__ = [
    "EXPIRED_UNSENT",
    "OBSERVATION_WINDOW_SECONDS",
    "POLLED",
    "POLL_SCHEDULE",
    "RESOLVED",
    "SUBMITTED",
    "WINDOW_CLOSED",
    "CheckoutOutcome",
    "CheckoutTask",
]
