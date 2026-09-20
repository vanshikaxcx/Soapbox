"""The provider's typed operations (WP-09).

Five of them, and the shape of the set is the point:

    Payment.submit / Payment.query
    Order.create   / Order.get
                     Refund.query

There is deliberately **no** ``Refund.initiate`` and no ``Order.update``. ProofPath
never initiates a refund -- refunds exist only as facts that arrive from the
provider -- which is why WP-02's refund machine has no initiation event. The
absence is the feature.

``Order.create`` is the one write recovery must never reach. It lives here with
the other writes so the import graph can be checked: anything that can only read
imports ``provider_read``, never this module.
"""

from __future__ import annotations

from datetime import datetime

from services.application.ports import Clock, IdFactory
from services.domain.errors import PaymentKeyConflict
from services.domain.ids import Record
from services.domain.money import Currency, Money
from services.simulator.ledger import (
    LedgerStatus,
    OrderRecord,
    PaymentRecord,
    RefundRecord,
    Scenario,
)


class SubmitRequest(Record):
    """Exactly the terms that were approved. Nothing else may be sent."""

    provider: str = "sim"
    payment_key: str
    request_hash: str
    quote_hash: str
    seller_id: str
    amount: Money
    currency: Currency = Currency.INR
    expires_at: datetime


class OrderRequest(Record):
    provider: str = "sim"
    order_key: str
    payment_reference: str
    quote_hash: str


class NotFound(Record):
    """The provider has no record of this key. Not an error -- an answer."""

    key: str


class ResponseLost(Exception):
    """The effect was recorded and then the reply failed to arrive.

    Raised, not returned, because that is how a lost response actually presents
    itself to a caller: as a transport failure, with no information about whether
    anything happened. The whole product exists to survive this.
    """

    def __init__(self, payment_key: str) -> None:
        super().__init__(f"response lost for {payment_key}")
        self.payment_key = payment_key


SubmitResult = PaymentRecord | PaymentKeyConflict
QueryResult = PaymentRecord | NotFound


class Simulator:
    """The provider. Owns its ledger and is the only thing that writes to it."""

    def __init__(
        self, *, clock: Clock, ids: IdFactory, scenario: Scenario = Scenario.SUCCESS
    ) -> None:
        self._clock = clock
        self._ids = ids
        self._scenario = scenario
        self._payments: dict[tuple[str, str], PaymentRecord] = {}
        self._orders: dict[tuple[str, str], OrderRecord] = {}
        self._refunds: dict[tuple[str, str], object] = {}
        self.submissions_received = 0
        self.duplicate_submissions_suppressed = 0
        self.callbacks_sent = 0

    # -- operator control --------------------------------------------------

    def set_scenario(self, scenario: Scenario) -> None:
        """Operator-only. Authorization is checked before this is reached."""
        self._scenario = scenario

    @property
    def scenario(self) -> Scenario:
        return self._scenario

    # -- payment -----------------------------------------------------------

    def submit(self, request: SubmitRequest) -> SubmitResult:
        """Take a payment, once.

        The three branches below are the whole idempotency story, and their order
        matters: identity first, then payload, then expiry. Checking expiry first
        would let a replay of an accepted payment be rejected after the fact,
        which would tell the caller a payment failed that in fact succeeded.
        """
        self.submissions_received += 1
        key = (request.provider, request.payment_key)
        existing = self._payments.get(key)

        if existing is not None:
            if existing.request_hash != request.request_hash:
                # Same key, different terms. No write, no effect.
                return PaymentKeyConflict(payment_key=request.payment_key)
            # An identical replay. The original facts, even after expiry.
            self.duplicate_submissions_suppressed += 1
            return existing

        now = self._clock.now()
        if now >= request.expires_at:
            # Unseen key, already too late. The rejection is itself durable, so a
            # later replay gets the same answer rather than being accepted late.
            rejection = PaymentRecord(
                provider=request.provider,
                payment_key=request.payment_key,
                request_hash=request.request_hash,
                seller_id=request.seller_id,
                amount=request.amount,
                currency=request.currency,
                expires_at=request.expires_at,
                status=LedgerStatus.EXPIRED_REJECTED,
                provider_reference=None,
                scenario=self._scenario,
                effect_recorded=False,
                created_at=now,
            )
            self._payments[key] = rejection
            return rejection

        record = PaymentRecord(
            provider=request.provider,
            payment_key=request.payment_key,
            request_hash=request.request_hash,
            seller_id=request.seller_id,
            amount=request.amount,
            currency=request.currency,
            expires_at=request.expires_at,
            status=self._status_for_scenario(),
            provider_reference=self._ids.new_id("payref"),
            scenario=self._scenario,
            effect_recorded=True,
            created_at=now,
        )
        self._payments[key] = record

        if self._scenario is Scenario.ACCEPT_THEN_TIMEOUT:
            # The effect is committed and THEN the reply fails. This is the exact
            # shape the product is built to survive, and the reason the dispatch
            # marker has to be written before the call rather than after.
            raise ResponseLost(request.payment_key)

        return record

    def query(self, *, provider: str = "sim", payment_key: str) -> QueryResult:
        """Read-only. The safe thing to do after an ambiguous dispatch."""
        record = self._payments.get((provider, payment_key))
        return record if record is not None else NotFound(key=payment_key)

    def _status_for_scenario(self) -> LedgerStatus:
        if self._scenario is Scenario.DEFINITIVE_FAILURE:
            return LedgerStatus.FAILED
        if self._scenario is Scenario.ACCEPT_THEN_TIMEOUT:
            return LedgerStatus.SUCCEEDED
        return LedgerStatus.SUCCEEDED

    # -- order -------------------------------------------------------------

    def create_order(self, request: OrderRequest) -> OrderRecord | NotFound:
        """Idempotent on ``order_key``. Checkout only -- recovery never reaches this.

        Under PAID_ORDER_MISSING the provider took the money and simply has no
        order. It returns NotFound rather than raising, because "we cannot find
        your order" is a fact to be recorded, not a system error to be retried.
        """
        key = (request.provider, request.order_key)
        existing = self._orders.get(key)
        if existing is not None:
            return existing

        if self._scenario is Scenario.PAID_ORDER_MISSING:
            return NotFound(key=request.order_key)

        record = OrderRecord(
            provider=request.provider,
            order_key=request.order_key,
            payment_reference=request.payment_reference,
            quote_hash=request.quote_hash,
            order_reference=self._ids.new_id("ordref"),
            created_at=self._clock.now(),
        )
        self._orders[key] = record
        return record

    def get_order(self, *, provider: str = "sim", order_key: str) -> OrderRecord | NotFound:
        record = self._orders.get((provider, order_key))
        return record if record is not None else NotFound(key=order_key)

    # -- refund ------------------------------------------------------------

    def query_refund(self, *, provider: str = "sim", refund_reference: str) -> object:
        """Read-only, always. There is no operation here that starts a refund."""
        record = self._refunds.get((provider, refund_reference))
        return record if record is not None else NotFound(key=refund_reference)

    def seed_refund(self, record: RefundRecord) -> None:
        """Operator-side: a refund appears because the provider made one."""
        self._refunds[(record.provider, record.refund_reference)] = record

    # -- evidence for the demo --------------------------------------------

    def effect_count(self) -> int:
        """Payments that actually happened. Rejections are not effects."""
        return sum(1 for r in self._payments.values() if r.effect_recorded)

    def order_effect_count(self) -> int:
        return len(self._orders)

    def rejection_count(self) -> int:
        return sum(1 for r in self._payments.values() if not r.effect_recorded)


__all__ = [
    "NotFound",
    "OrderRequest",
    "QueryResult",
    "ResponseLost",
    "Simulator",
    "SubmitRequest",
    "SubmitResult",
]
