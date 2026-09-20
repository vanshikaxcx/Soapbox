"""Opening a case, and ingesting a provider callback (WP-09).

Two things that were previously only flags and contracts:

- ``open_case`` actually writes a ``Case``. The checkout task used to return
  ``case_opened=True`` and store nothing, so nothing downstream could read it.
- ``ingest_callback`` runs the full path a delivery takes: verify, record the
  inbox row, decide a disposition, and apply the fact through WP-02's rules.

P4 implements the HTTP endpoint in WP-10; this is the behaviour behind it, so
both sides can be tested against the same fixtures before they meet.

A case states what is **known** and what is **missing**. The missing list is a
first-class field rather than an absence, because "we cannot tell whether an
order exists" is the sentence a shopper most needs said out loud.
"""

from __future__ import annotations

from datetime import datetime

from services.application.callbacks import (
    CallbackBody,
    CallbackHeaders,
    Disposition,
    FactKind,
    Rejection,
    Verified,
    disposition_of,
    verify,
)
from services.application.ports import Clock, Condition, IdFactory, StateStore, Write
from services.application.purchase import NotFound, purchase_key
from services.domain.errors import DomainError
from services.domain.evidence import Case, InboxEvent, MissingFact
from services.domain.evidence import FactKind as DomainFactKind
from services.domain.ids import Record
from services.domain.provider import (
    Applied,
    Current,
    apply_payment_facts,
    apply_refund_facts,
)
from services.domain.provider import PaymentFacts as DomainPaymentFacts
from services.domain.provider import RefundFacts as DomainRefundFacts
from services.domain.purchase import ProviderLookup, Purchase
from services.domain.transitions import (
    InboxState,
    OrderState,
    PaymentState,
    RefundState,
)

_REFUND_FROM_STATUS = {
    "pending": RefundState.PENDING,
    "completed": RefundState.COMPLETED,
    "failed": RefundState.FAILED,
    "unknown": RefundState.UNKNOWN,
}

_PAYMENT_FROM_STATUS = {
    "succeeded": PaymentState.SUCCEEDED,
    "failed": PaymentState.FAILED,
    "pending": PaymentState.PENDING,
    "unknown": PaymentState.UNKNOWN,
    "accepted": PaymentState.PENDING,
}


def case_key(purchase_id: str) -> tuple[str, str]:
    return (f"PURCHASE#{purchase_id}", "CASE")


def inbox_key(provider: str, event_id: str) -> tuple[str, str]:
    return (f"INBOX#{provider}#{event_id}", "EVENT")


class CallbackResult(Record):
    """What happened to one delivery. ``accepted`` means we durably recorded it."""

    accepted: bool
    disposition: Disposition | None = None
    rejection: Rejection | None = None
    applied_payment: PaymentState | None = None
    case_opened: bool = False
    detail: str = ""


def missing_facts_for(purchase: Purchase) -> tuple[MissingFact, ...]:
    """Name the gaps, rather than leaving them as an absence.

    A shopper reading a case needs to see the questions, not infer them from
    fields that happen to be empty.
    """
    missing: list[MissingFact] = []
    if purchase.payment in (PaymentState.UNKNOWN, PaymentState.PENDING, PaymentState.CLAIMED):
        missing.append(MissingFact.PAYMENT_OUTCOME)
    if purchase.payment is PaymentState.SUCCEEDED and purchase.order is not (OrderState.CONFIRMED):
        missing.append(MissingFact.ORDER_EXISTENCE)
        missing.append(MissingFact.ORDER_REFERENCE)
    return tuple(missing)


def known_facts_for(purchase: Purchase) -> tuple[DomainFactKind, ...]:
    known: list[DomainFactKind] = []
    if purchase.payment in (PaymentState.SUCCEEDED, PaymentState.FAILED):
        known.append(DomainFactKind.PAYMENT)
    if purchase.order in (OrderState.CONFIRMED, OrderState.FAILED):
        known.append(DomainFactKind.ORDER)
    return tuple(known)


class CaseService:
    """Opens and updates cases. Never touches a provider."""

    def __init__(self, *, store: StateStore, clock: Clock, ids: IdFactory) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def open_case(self, *, purchase_id: str) -> Case | DomainError:
        """Write the case the checkout task asked for.

        Idempotent: a purchase has one case, and reopening an existing one
        refreshes its facts rather than creating a second.
        """
        purchase = self._store.get(purchase_key(purchase_id))
        if not isinstance(purchase, Purchase):
            return NotFound("purchase")

        existing = self._store.get(case_key(purchase_id))
        now = self._clock.now()

        if isinstance(existing, Case):
            refreshed = existing.model_copy(
                update={
                    "known_facts": known_facts_for(purchase),
                    "missing_facts": missing_facts_for(purchase),
                    "version": existing.version + 1,
                }
            )
            failure = self._store.transact(
                [
                    Write(
                        key=case_key(purchase_id),
                        item=refreshed,
                        condition=Condition.VERSION_MUST_BE,
                        expected_version=existing.version,
                        reason="refresh what we know and what we still do not",
                    )
                ]
            )
            return failure if failure is not None else refreshed

        case = Case(
            case_id=self._ids.new_id("case"),
            purchase_id=purchase_id,
            owner_id=purchase.owner_id,
            opened_at=now,
            known_facts=known_facts_for(purchase),
            missing_facts=missing_facts_for(purchase),
        )
        failure = self._store.transact(
            [
                Write(
                    key=case_key(purchase_id),
                    item=case,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="one case per purchase",
                )
            ]
        )
        return failure if failure is not None else case

    def read_case(self, *, owner_id: str, purchase_id: str) -> Case | DomainError:
        case = self._store.get(case_key(purchase_id))
        if not isinstance(case, Case) or case.owner_id != owner_id:
            return NotFound("case")
        return case


class CallbackIngest:
    """The full path a provider delivery takes. P4 wraps this in an endpoint."""

    def __init__(self, *, store: StateStore, clock: Clock, ids: IdFactory, secret: bytes) -> None:
        self._store = store
        self._clock = clock
        self._secret = secret
        self._cases = CaseService(store=store, clock=clock, ids=ids)

    def ingest(
        self, *, headers: CallbackHeaders, raw_body: bytes, body: CallbackBody
    ) -> CallbackResult:
        now = self._clock.now()

        verified = verify(secret=self._secret, headers=headers, raw_body=raw_body, now=now)
        if isinstance(verified, Rejection):
            # Nothing is recorded. A delivery that cannot be authenticated never
            # touches state, whatever it claims about itself.
            return CallbackResult(accepted=False, rejection=verified, detail=f"refused: {verified}")

        existing = self._store.get(inbox_key(verified.provider, verified.event_id))
        existing_hash = existing.body_hash if isinstance(existing, InboxEvent) else None

        lookup = self._find_lookup(body.key)
        disposition = disposition_of(
            verified=verified, existing_body_hash=existing_hash, lookup=lookup, body=body
        )

        if existing_hash is None:
            # Durability precedes acknowledgement: the row goes down before we
            # would return 2xx, so a provider that got an ack never needs to
            # redeliver on our account.
            self._record_inbox(verified, body, disposition, now)

        if disposition is not Disposition.APPLIED or lookup is None:
            return CallbackResult(
                accepted=True, disposition=disposition, detail=f"recorded as {disposition}"
            )

        return self._apply(verified, body, lookup, disposition, now)

    # -- internals ---------------------------------------------------------

    def _find_lookup(self, payment_key: str) -> ProviderLookup | None:
        from services.application.purchase import provider_lookup_key

        found = self._store.get(provider_lookup_key(payment_key))
        return found if isinstance(found, ProviderLookup) else None

    def _record_inbox(
        self,
        verified: Verified,
        body: CallbackBody,
        disposition: Disposition,
        now: datetime,
    ) -> None:
        event = InboxEvent(
            provider=verified.provider,
            event_id=verified.event_id,
            body_hash=verified.body_hash,
            delivery_timestamp=verified.delivery_timestamp,
            received_at=now,
            kind=DomainFactKind(body.kind.value),
            key=body.key,
            status=_INBOX_STATUS[disposition],
        )
        self._store.transact(
            [
                Write(
                    key=inbox_key(verified.provider, verified.event_id),
                    item=event,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="the delivery is recorded before it is acknowledged",
                )
            ]
        )

    def _apply(
        self,
        verified: Verified,
        body: CallbackBody,
        lookup: ProviderLookup,
        disposition: Disposition,
        now: datetime,
    ) -> CallbackResult:
        purchase = self._store.get(purchase_key(lookup.purchase_id))
        if not isinstance(purchase, Purchase):
            return CallbackResult(
                accepted=True,
                disposition=Disposition.QUARANTINED,
                detail="the purchase this names does not exist",
            )

        if body.kind is FactKind.REFUND:
            return self._apply_refund(purchase, body, disposition)

        if body.kind is not FactKind.PAYMENT:
            return CallbackResult(
                accepted=True, disposition=disposition, detail=f"{body.kind} fact recorded"
            )

        incoming = _PAYMENT_FROM_STATUS.get(body.status)
        if incoming is None:
            return CallbackResult(
                accepted=True,
                disposition=Disposition.QUARANTINED,
                detail=f"unrecognised status {body.status!r}",
            )

        result = apply_payment_facts(
            Current(state=purchase.payment, observed_at=None),
            DomainPaymentFacts(
                state=incoming,
                observed_at=body.observed_at,
                reference=body.reference,
                amount=lookup.expected_amount,
                seller_id=body.seller_id,
            ),
        )

        if not isinstance(result, Applied):
            # Stale or contradictory. WP-02 decided; we record and change nothing.
            return CallbackResult(
                accepted=True, disposition=Disposition.QUARANTINED, detail=type(result).__name__
            )

        if not isinstance(result.state, PaymentState):
            return CallbackResult(
                accepted=True,
                disposition=Disposition.QUARANTINED,
                detail="fact applied to the wrong machine",
            )
        settled = result.state
        if result.changed:
            self._persist(purchase, settled)
            purchase = purchase.model_copy(
                update={"payment": settled, "version": purchase.version + 1}
            )

        case_opened = False
        if settled is PaymentState.SUCCEEDED and purchase.order is not (OrderState.CONFIRMED):
            # Paid, no order. Open the case rather than leaving a flag nobody reads.
            self._cases.open_case(purchase_id=purchase.purchase_id)
            case_opened = True

        return CallbackResult(
            accepted=True,
            disposition=disposition,
            applied_payment=settled,
            case_opened=case_opened,
            detail="applied",
        )

    def _apply_refund(
        self, purchase: Purchase, body: CallbackBody, disposition: Disposition
    ) -> CallbackResult:
        """A refund exists only because the provider made one.

        ProofPath never initiates one, so this path only ever records what
        arrived. It goes through WP-02's rules like every other fact, which is
        what stops a stale ``pending`` landing after ``completed``.
        """
        incoming = _REFUND_FROM_STATUS.get(body.status)
        if incoming is None:
            return CallbackResult(
                accepted=True,
                disposition=Disposition.QUARANTINED,
                detail=f"unrecognised refund status {body.status!r}",
            )

        result = apply_refund_facts(
            Current(state=purchase.refund, observed_at=None),
            DomainRefundFacts(
                state=incoming, observed_at=body.observed_at, reference=body.reference
            ),
        )
        if not isinstance(result, Applied):
            return CallbackResult(
                accepted=True, disposition=Disposition.QUARANTINED, detail=type(result).__name__
            )

        if result.changed and isinstance(result.state, RefundState):
            updated = purchase.model_copy(
                update={
                    "refund": result.state,
                    "version": purchase.version + 1,
                }
            )
            self._store.transact(
                [
                    Write(
                        key=purchase_key(purchase.purchase_id),
                        item=updated,
                        condition=Condition.VERSION_MUST_BE,
                        expected_version=purchase.version,
                        reason="record the refund the provider reported",
                    )
                ]
            )
        return CallbackResult(
            accepted=True, disposition=disposition, detail=f"refund {result.state}"
        )

    def _persist(self, purchase: Purchase, payment: PaymentState) -> None:
        updated = purchase.model_copy(
            update={
                "payment": payment,
                "version": purchase.version + 1,
            }
        )
        self._store.transact(
            [
                Write(
                    key=purchase_key(purchase.purchase_id),
                    item=updated,
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=purchase.version,
                    reason="apply the provider's fact",
                )
            ]
        )


_INBOX_STATUS = {
    Disposition.APPLIED: InboxState.APPLIED,
    Disposition.DUPLICATE: InboxState.DUPLICATE,
    Disposition.CONFLICTED: InboxState.CONFLICTED,
    Disposition.QUARANTINED: InboxState.QUARANTINED,
}


__all__ = [
    "CallbackIngest",
    "CallbackResult",
    "CaseService",
    "case_key",
    "inbox_key",
    "known_facts_for",
    "missing_facts_for",
]
