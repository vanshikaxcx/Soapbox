"""Reconciliation: ask the provider what actually happened (WP-09).

Reads the references we already hold and applies whatever the provider currently
reports. It **creates nothing**: no payment, no order, no refund, no attempt.

That is enforced by construction rather than by care. This module takes a
``ProviderReadPort``, and the read port has no write verb on it -- so there is no
call to accidentally make, and a test asserts the import graph rather than
trusting a reviewer to notice.

Fact application goes through WP-02's rules, so the guarantees hold here too: a
terminal state is never revised, a late ``pending`` cannot downgrade a success,
and two disagreeing terminal facts quarantine instead of one of them winning.
"""

from __future__ import annotations

from datetime import datetime

from services.application.ports import Clock, Condition, StateStore, Write
from services.application.provider_ports import (
    OrderFacts,
    PaymentFacts,
    ProviderNotFound,
    ProviderPaymentStatus,
    ProviderReadPort,
)
from services.application.purchase import (
    NotFound,
    attempt_key,
    provider_lookup_key,
    purchase_key,
)
from services.domain.errors import ContradictoryProviderFact, DomainError, FactIgnoredStale
from services.domain.ids import Id, Record
from services.domain.keys import order_key as derive_order_key
from services.domain.provider import Applied, Current, apply_order_facts, apply_payment_facts
from services.domain.provider import OrderFacts as DomainOrderFacts
from services.domain.provider import PaymentFacts as DomainPaymentFacts
from services.domain.purchase import Attempt, ProviderLookup, Purchase
from services.domain.transitions import OrderState, PaymentState

_PAYMENT = {
    ProviderPaymentStatus.ACCEPTED: PaymentState.PENDING,
    ProviderPaymentStatus.PENDING: PaymentState.PENDING,
    ProviderPaymentStatus.SUCCEEDED: PaymentState.SUCCEEDED,
    ProviderPaymentStatus.FAILED: PaymentState.FAILED,
    ProviderPaymentStatus.EXPIRED_REJECTED: PaymentState.FAILED,
}


class Reconciliation(Record):
    """What the provider says now, and whether it changed anything."""

    purchase_id: Id
    payment: PaymentState
    order: OrderState
    changed: bool = False
    quarantined: bool = False
    case_opened: bool = False
    detail: str = ""


class ReconcileTask:
    """Read-only against the provider. Writes only our own records."""

    def __init__(self, *, store: StateStore, clock: Clock, provider: ProviderReadPort) -> None:
        self._store = store
        self._clock = clock
        #: A ProviderReadPort. Handing this a write port would still work, but
        #: the isolation test asserts the module never imports one.
        self._provider = provider

    def run(self, *, owner_id: str, purchase_id: str) -> Reconciliation | DomainError:
        purchase = self._store.get(purchase_key(purchase_id))
        if not isinstance(purchase, Purchase) or purchase.owner_id != owner_id:
            return NotFound("purchase")

        attempt_id = purchase.last_attempt_id or purchase.active_attempt_id
        if attempt_id is None:
            return Reconciliation(
                purchase_id=purchase_id,
                payment=purchase.payment,
                order=purchase.order,
                detail="nothing was ever dispatched",
            )

        attempt = self._store.get(attempt_key(purchase_id, attempt_id))
        if not isinstance(attempt, Attempt):
            return NotFound("attempt")

        lookup = self._store.get(provider_lookup_key(attempt.payment_key))
        now = self._clock.now()

        payment, quarantined, detail = self._reconcile_payment(purchase, attempt, lookup, now)
        order = self._reconcile_order(purchase, attempt, payment, now)

        changed = payment != purchase.payment or order != purchase.order
        if changed:
            self._persist(purchase, payment, order)

        return Reconciliation(
            purchase_id=purchase_id,
            payment=payment,
            order=order,
            changed=changed,
            quarantined=quarantined,
            case_opened=payment is PaymentState.SUCCEEDED and order is not (OrderState.CONFIRMED),
            detail=detail,
        )

    # -- payment -----------------------------------------------------------

    def _reconcile_payment(
        self, purchase: Purchase, attempt: Attempt, lookup: object, now: datetime
    ) -> tuple[PaymentState, bool, str]:
        found = self._provider.query_payment(payment_key=attempt.payment_key)
        if isinstance(found, ProviderNotFound):
            return purchase.payment, False, "the provider has no record of this payment"
        if not isinstance(found, PaymentFacts):
            return purchase.payment, False, "no usable payment facts"

        if isinstance(lookup, ProviderLookup) and not lookup.matches(
            seller_id=found.seller_id, amount=found.amount, currency=found.currency
        ):
            # Terms we never approved. Never applied, whatever it claims.
            return purchase.payment, True, "provider facts did not match the lookup"

        result = apply_payment_facts(
            Current(state=purchase.payment, observed_at=attempt.started_at),
            DomainPaymentFacts(
                state=_PAYMENT[found.status],
                observed_at=now,
                reference=found.provider_reference,
                amount=found.amount,
                seller_id=found.seller_id,
            ),
        )
        if isinstance(result, Applied) and isinstance(result.state, PaymentState):
            return result.state, False, "payment reconciled"
        if isinstance(result, ContradictoryProviderFact):
            return purchase.payment, True, "contradictory terminal payment facts"
        if isinstance(result, FactIgnoredStale):
            return purchase.payment, False, "provider fact was older than what we hold"
        return purchase.payment, False, "payment unchanged"

    # -- order -------------------------------------------------------------

    def _reconcile_order(
        self,
        purchase: Purchase,
        attempt: Attempt,
        payment: PaymentState,
        now: datetime,
    ) -> OrderState:
        found = self._provider.get_order(
            order_key=derive_order_key(
                purchase_id=purchase.purchase_id, attempt_id=attempt.attempt_id
            )
        )
        if not isinstance(found, OrderFacts):
            # No order. We do NOT create one -- that is the whole point of this
            # path. Paid with no order is a fact to record, not a gap to fill.
            return purchase.order

        result = apply_order_facts(
            Current(state=purchase.order, observed_at=attempt.started_at),
            DomainOrderFacts(
                state=OrderState.CONFIRMED, observed_at=now, reference=found.order_reference
            ),
        )
        if isinstance(result, Applied) and isinstance(result.state, OrderState):
            return result.state
        return purchase.order

    # -- persistence -------------------------------------------------------

    def _persist(self, purchase: Purchase, payment: PaymentState, order: OrderState) -> None:
        updated = purchase.model_copy(
            update={
                "payment": payment,
                "order": order,
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
                    reason="record what the provider says now",
                )
            ]
        )


__all__ = ["ReconcileTask", "Reconciliation"]
