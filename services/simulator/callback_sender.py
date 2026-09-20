"""The simulator calling us back (WP-09).

A real provider does not hand you the outcome on the same connection it took the
payment on. It calls you back, minutes later, possibly twice, possibly out of
order, and occasionally with a body that disagrees with the one it sent before.
This produces exactly those deliveries so the fault scenarios are demonstrable
rather than merely named in an enum.

It lives in the simulator because a callback is a thing the *provider* does. It
signs with the shared secret and speaks the envelope WP-09 defined, so the
deliveries it produces are the same shape P4's endpoint will receive in WP-10.
"""

from __future__ import annotations

import json
from datetime import datetime

from services.application.callbacks import (
    CallbackBody,
    CallbackHeaders,
    FactKind,
    _timestamp_text,
    sign,
)
from services.domain.ids import Record
from services.domain.money import Currency, Money
from services.simulator.ledger import LedgerStatus, PaymentRecord, Scenario


class Delivery(Record):
    """One callback, ready to post. Raw bytes included, because the signature
    covers those and not a re-serialised object."""

    headers: CallbackHeaders
    raw_body: bytes
    body: CallbackBody

    model_config = Record.model_config | {"arbitrary_types_allowed": True}


class CallbackSender:
    """Turns a recorded payment into the deliveries its scenario implies."""

    def __init__(self, *, secret: bytes, provider: str = "sim") -> None:
        self._secret = secret
        self._provider = provider

    def deliveries_for(
        self, payment: PaymentRecord, *, at: datetime, scenario: Scenario
    ) -> tuple[Delivery, ...]:
        """What this provider would send about this payment, in order."""
        if not payment.effect_recorded:
            # Nothing happened, so there is nothing to call back about.
            return ()

        if scenario is Scenario.DUPLICATE_CALLBACK:
            # The same event, twice. A provider retrying because it never saw our
            # 2xx. The second must change nothing.
            first = self._payment_delivery(payment, at=at, event_id="evt-dup-1")
            return (first, self._resign(first, at=at))

        if scenario is Scenario.CONFLICTING_CALLBACK:
            # One event id, two different bodies. Somebody is replaying an id with
            # a changed body, and it must never be applied.
            event_id = "evt-conflict-1"
            honest = self._payment_delivery(payment, at=at, event_id=event_id)
            lie = self._payment_delivery(
                payment,
                at=at,
                event_id=event_id,
                status="failed",
            )
            return (honest, lie)

        if scenario is Scenario.REFUND_PENDING_THEN_COMPLETE:
            # Payment succeeded, then a refund arrives in two stages. ProofPath
            # never asked for it -- refunds only ever appear as provider facts.
            return (
                self._payment_delivery(payment, at=at, event_id="evt-pay-1"),
                self._refund_delivery(payment, at=at, event_id="evt-refund-1", status="pending"),
                self._refund_delivery(payment, at=at, event_id="evt-refund-2", status="completed"),
            )

        return (self._payment_delivery(payment, at=at, event_id="evt-pay-1"),)

    # -- building one delivery --------------------------------------------

    def _payment_delivery(
        self,
        payment: PaymentRecord,
        *,
        at: datetime,
        event_id: str,
        status: str | None = None,
    ) -> Delivery:
        return self._build(
            kind=FactKind.PAYMENT,
            key=payment.payment_key,
            event_id=event_id,
            status=status or _STATUS_TEXT[payment.status],
            amount=payment.amount,
            seller_id=payment.seller_id,
            reference=payment.provider_reference,
            at=at,
        )

    def _refund_delivery(
        self, payment: PaymentRecord, *, at: datetime, event_id: str, status: str
    ) -> Delivery:
        return self._build(
            kind=FactKind.REFUND,
            key=payment.payment_key,
            event_id=event_id,
            status=status,
            amount=payment.amount,
            seller_id=payment.seller_id,
            reference=f"refund-{payment.payment_key[:12]}",
            at=at,
        )

    def _build(
        self,
        *,
        kind: FactKind,
        key: str,
        event_id: str,
        status: str,
        amount: Money,
        seller_id: str,
        reference: str | None,
        at: datetime,
    ) -> Delivery:
        payload = {
            "event_id": event_id,
            "provider": self._provider,
            "kind": kind.value,
            "key": key,
            "reference": reference,
            "status": status,
            "amount_paise": amount.amount_paise,
            "currency": str(Currency.INR),
            "seller_id": seller_id,
            "observed_at": _timestamp_text(at),
        }
        # Compact, deterministic bytes. Whatever these are, they are what gets
        # signed -- the signature never covers a re-serialised object.
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers = CallbackHeaders(
            provider=self._provider,
            event_id=event_id,
            delivery_timestamp=at,
            signature=sign(
                secret=self._secret,
                delivery_timestamp=_timestamp_text(at),
                event_id=event_id,
                raw_body=raw,
            ),
        )
        body = CallbackBody(
            event_id=event_id,
            provider=self._provider,
            kind=kind,
            key=key,
            reference=reference,
            status=status,
            amount_paise=amount.amount_paise,
            currency=Currency.INR,
            seller_id=seller_id,
            observed_at=at,
        )
        return Delivery(headers=headers, raw_body=raw, body=body)

    def _resign(self, delivery: Delivery, *, at: datetime) -> Delivery:
        """A redelivery: same event, same bytes, fresh timestamp and signature.

        The timestamp is refreshed on every attempt, so a captured signature
        cannot be replayed later -- and the receiver still recognises the event
        as one it has already seen, because that is keyed on the id and body.
        """
        stamp = _timestamp_text(at)
        headers = delivery.headers.model_copy(
            update={
                "delivery_timestamp": at,
                "signature": sign(
                    secret=self._secret,
                    delivery_timestamp=stamp,
                    event_id=delivery.headers.event_id,
                    raw_body=delivery.raw_body,
                ),
            }
        )
        return Delivery(headers=headers, raw_body=delivery.raw_body, body=delivery.body)


_STATUS_TEXT = {
    LedgerStatus.ACCEPTED: "accepted",
    LedgerStatus.PENDING: "pending",
    LedgerStatus.SUCCEEDED: "succeeded",
    LedgerStatus.FAILED: "failed",
    LedgerStatus.EXPIRED_REJECTED: "failed",
}


__all__ = ["CallbackSender", "Delivery"]
