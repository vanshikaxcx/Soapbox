"""The payment provider, as the application sees it (WP-09).

Split into a **read** port and a **write** port, in that order of importance.
Recovery and reconciliation may depend on the read port and must not be able to
reach the write port at all -- which is why they are separate types here rather
than one interface with a comment asking people to be careful. "Recovery creates
no commerce effect" then becomes a property of the import graph, checkable by a
test, instead of a promise.

The vocabulary here is the application's, not the provider's. Translating a
provider's own status words into these is the adapter's job, so a second
provider could be added without touching the checkout task.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field

from services.domain.ids import Record
from services.domain.money import Currency, Money


class ProviderPaymentStatus(StrEnum):
    """What a provider can tell us about a payment.

    ``EXPIRED_REJECTED`` is the one with no obvious domain twin: it means we DID
    call and were refused because the quote had expired. That is a definitive
    failure with no effect -- which is not the same as never having called.
    """

    ACCEPTED = "accepted"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED_REJECTED = "expired_rejected"


class PaymentFacts(Record):
    payment_key: str = Field(min_length=1, max_length=128)
    status: ProviderPaymentStatus
    provider_reference: str | None = None
    seller_id: str = Field(min_length=1, max_length=64)
    amount: Money
    currency: Currency = Currency.INR
    #: False only for a rejection that recorded nothing.
    effect_recorded: bool = True


class OrderFacts(Record):
    order_key: str = Field(min_length=1, max_length=128)
    order_reference: str = Field(min_length=1, max_length=128)
    status: str = Field(default="confirmed", min_length=1, max_length=32)


class SubmitRequest(Record):
    """Exactly the approved terms. Nothing else may ever be sent."""

    payment_key: str = Field(min_length=1, max_length=128)
    request_hash: str = Field(min_length=1, max_length=128)
    quote_hash: str = Field(min_length=1, max_length=128)
    seller_id: str = Field(min_length=1, max_length=64)
    amount: Money
    currency: Currency = Currency.INR
    expires_at: datetime


class OrderRequest(Record):
    order_key: str = Field(min_length=1, max_length=128)
    payment_reference: str = Field(min_length=1, max_length=128)
    quote_hash: str = Field(min_length=1, max_length=128)


class ProviderNotFound(Record):
    """The provider has no record of this key. An answer, not an error."""

    key: str


class ProviderConflict(Record):
    """Same key, different terms. Nothing was written."""

    key: str


class ResponseLost(Exception):
    """The call went out and no answer came back.

    Raised rather than returned, because that is how it actually presents itself
    to a caller: as a transport failure carrying no information about whether
    anything happened. Surviving this is the entire point of the product.
    """

    def __init__(self, payment_key: str) -> None:
        super().__init__(f"response lost for {payment_key}")
        self.payment_key = payment_key


@runtime_checkable
class ProviderReadPort(Protocol):
    """Everything recovery is allowed to do. Note the absence of any verb."""

    def query_payment(self, *, payment_key: str) -> PaymentFacts | ProviderNotFound: ...

    def get_order(self, *, order_key: str) -> OrderFacts | ProviderNotFound: ...

    def query_refund(self, *, refund_reference: str) -> object | ProviderNotFound: ...


@runtime_checkable
class ProviderWritePort(ProviderReadPort, Protocol):
    """Checkout only. Recovery must have no import path to this type."""

    def submit(self, request: SubmitRequest) -> PaymentFacts | ProviderConflict: ...

    def create_order(self, request: OrderRequest) -> OrderFacts | ProviderNotFound: ...

    def effect_count(self) -> int: ...


__all__ = [
    "OrderFacts",
    "OrderRequest",
    "PaymentFacts",
    "ProviderConflict",
    "ProviderNotFound",
    "ProviderPaymentStatus",
    "ProviderReadPort",
    "ProviderWritePort",
    "ResponseLost",
    "SubmitRequest",
]
