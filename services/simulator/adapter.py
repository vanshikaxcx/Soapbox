"""The simulator, wearing the provider ports (WP-09).

This is the only place that knows both vocabularies. The ledger speaks
``LedgerStatus``; the application speaks ``ProviderPaymentStatus``. Translating
between them is an adapter's job, so the checkout task never has to know that
this particular provider calls a refusal ``expired_rejected``.

Dependency direction: an adapter may import the application's ports. The
application must never import this module -- a boundary test enforces that.
"""

from __future__ import annotations

from services.application.provider_ports import (
    OrderFacts,
    OrderRequest,
    PaymentFacts,
    ProviderConflict,
    ProviderNotFound,
    ProviderPaymentStatus,
    ProviderReadPort,
    ResponseLost,
    SubmitRequest,
)
from services.domain.errors import PaymentKeyConflict
from services.simulator.ledger import LedgerStatus, OrderRecord, PaymentRecord
from services.simulator.operations import NotFound as LedgerNotFound
from services.simulator.operations import OrderRequest as LedgerOrderRequest
from services.simulator.operations import ResponseLost as LedgerResponseLost
from services.simulator.operations import Simulator
from services.simulator.operations import SubmitRequest as LedgerSubmitRequest

_STATUS = {
    LedgerStatus.ACCEPTED: ProviderPaymentStatus.ACCEPTED,
    LedgerStatus.PENDING: ProviderPaymentStatus.PENDING,
    LedgerStatus.SUCCEEDED: ProviderPaymentStatus.SUCCEEDED,
    LedgerStatus.FAILED: ProviderPaymentStatus.FAILED,
    LedgerStatus.EXPIRED_REJECTED: ProviderPaymentStatus.EXPIRED_REJECTED,
}


class SimulatorProvider:
    """Implements ProviderWritePort over the simulator's ledger."""

    def __init__(self, simulator: Simulator) -> None:
        self._sim = simulator

    # -- write (checkout only) --------------------------------------------

    def submit(self, request: SubmitRequest) -> PaymentFacts | ProviderConflict:
        try:
            result = self._sim.submit(
                LedgerSubmitRequest(
                    payment_key=request.payment_key,
                    request_hash=request.request_hash,
                    quote_hash=request.quote_hash,
                    seller_id=request.seller_id,
                    amount=request.amount,
                    currency=request.currency,
                    expires_at=request.expires_at,
                )
            )
        except LedgerResponseLost as lost:
            # Re-raised in the application's own vocabulary so the checkout task
            # never has to import anything from the simulator.
            raise ResponseLost(lost.payment_key) from lost

        if isinstance(result, PaymentKeyConflict):
            return ProviderConflict(key=request.payment_key)
        return _facts(result)

    def create_order(self, request: OrderRequest) -> OrderFacts | ProviderNotFound:
        result = self._sim.create_order(
            LedgerOrderRequest(
                order_key=request.order_key,
                payment_reference=request.payment_reference,
                quote_hash=request.quote_hash,
            )
        )
        if isinstance(result, LedgerNotFound):
            return ProviderNotFound(key=request.order_key)
        return _order(result)

    def effect_count(self) -> int:
        return self._sim.effect_count()

    # -- read (checkout and recovery) -------------------------------------

    def query_payment(self, *, payment_key: str) -> PaymentFacts | ProviderNotFound:
        result = self._sim.query(payment_key=payment_key)
        if isinstance(result, LedgerNotFound):
            return ProviderNotFound(key=payment_key)
        return _facts(result)

    def get_order(self, *, order_key: str) -> OrderFacts | ProviderNotFound:
        result = self._sim.get_order(order_key=order_key)
        if isinstance(result, LedgerNotFound):
            return ProviderNotFound(key=order_key)
        return _order(result)

    def query_refund(self, *, refund_reference: str) -> object:
        result = self._sim.query_refund(refund_reference=refund_reference)
        if isinstance(result, LedgerNotFound):
            return ProviderNotFound(key=refund_reference)
        return result


class ReadOnlyProvider:
    """The same simulator with the write verbs removed.

    Handed to recovery and reconciliation. Even if someone reaches for
    ``submit`` there, it is not on this object -- the guarantee does not depend
    on them remembering not to.
    """

    def __init__(self, provider: ProviderReadPort) -> None:
        self._provider = provider

    def query_payment(self, *, payment_key: str) -> PaymentFacts | ProviderNotFound:
        return self._provider.query_payment(payment_key=payment_key)

    def get_order(self, *, order_key: str) -> OrderFacts | ProviderNotFound:
        return self._provider.get_order(order_key=order_key)

    def query_refund(self, *, refund_reference: str) -> object:
        return self._provider.query_refund(refund_reference=refund_reference)


def _facts(record: PaymentRecord) -> PaymentFacts:
    return PaymentFacts(
        payment_key=record.payment_key,
        status=_STATUS[record.status],
        provider_reference=record.provider_reference,
        seller_id=record.seller_id,
        amount=record.amount,
        currency=record.currency,
        effect_recorded=record.effect_recorded,
    )


def _order(record: OrderRecord) -> OrderFacts:
    return OrderFacts(
        order_key=record.order_key, order_reference=record.order_reference, status=record.status
    )


__all__ = ["ReadOnlyProvider", "SimulatorProvider"]
