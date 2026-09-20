"""The signed callback contract (WP-09).

P3 defines this; **P4 implements the HTTP endpoint** in WP-10. Everything a
handler has to decide is here as a pure function, so the two halves can be
verified against the same fixtures before they ever meet.

Verification order, which is also the order of the tests:

1. Known provider.
2. Timestamp skew within five minutes -- in **both** directions. A future
   timestamp is as suspicious as a stale one.
3. Signature valid, compared in constant time.
4. **Persist the immutable inbox row before returning 2xx.** Durability precedes
   acknowledgement: a provider that got a 2xx must never need to redeliver for
   our sake.
5. Only then resolve and apply.

The signing input is ``delivery_timestamp + "\\n" + event_id + "\\n" + raw_body``,
over the **raw bytes as received**. Never a re-serialised object: a JSON
round-trip reorders keys and changes whitespace, and the signature would fail for
an honest delivery while a tampered one that happened to round-trip identically
would pass.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from services.domain.canonical import body_hash
from services.domain.ids import Digest, Record
from services.domain.money import Currency, Money
from services.domain.purchase import ProviderLookup

#: A delivery timestamp further than this from now, in either direction, is refused.
MAX_SKEW_SECONDS = 300

HEADER_PROVIDER = "X-ProofPath-Provider"
HEADER_EVENT_ID = "X-ProofPath-Event-Id"
HEADER_TIMESTAMP = "X-ProofPath-Delivery-Timestamp"
HEADER_SIGNATURE = "X-ProofPath-Signature"

CONTRACT_VERSION = "proofpath.callback.v1"


class FactKind(StrEnum):
    PAYMENT = "payment"
    ORDER = "order"
    REFUND = "refund"


class Rejection(StrEnum):
    """Why a delivery was refused, before anything was recorded."""

    UNKNOWN_PROVIDER = "unknown_provider"
    SKEW_TOO_LARGE = "skew_too_large"
    BAD_SIGNATURE = "bad_signature"
    MALFORMED = "malformed"


class Disposition(StrEnum):
    """What happened to a delivery that passed verification."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    CONFLICTED = "conflicted"
    QUARANTINED = "quarantined"


class CallbackHeaders(Record):
    provider: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=128)
    delivery_timestamp: datetime
    signature: str = Field(min_length=1, max_length=128)


class CallbackBody(Record):
    """The JSON a provider posts. Data, never instruction."""

    event_id: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=64)
    kind: FactKind
    key: str = Field(min_length=1, max_length=128)
    reference: str | None = None
    status: str = Field(min_length=1, max_length=32)
    amount_paise: int = Field(ge=0)
    currency: Currency = Currency.INR
    seller_id: str = Field(min_length=1, max_length=64)
    observed_at: datetime


class Verified(Record):
    """A delivery whose signature and freshness hold. Not yet applied."""

    provider: str
    event_id: str
    body_hash: Digest
    delivery_timestamp: datetime


def signing_input(*, delivery_timestamp: str, event_id: str, raw_body: bytes) -> bytes:
    """The exact bytes that are signed. Order and separators are the contract."""
    if not isinstance(raw_body, (bytes, bytearray)):
        raise TypeError("the signature covers raw bytes, never a re-serialised object")
    return f"{delivery_timestamp}\n{event_id}\n".encode() + bytes(raw_body)


def sign(*, secret: bytes, delivery_timestamp: str, event_id: str, raw_body: bytes) -> str:
    payload = signing_input(
        delivery_timestamp=delivery_timestamp, event_id=event_id, raw_body=raw_body
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify(
    *,
    secret: bytes,
    headers: CallbackHeaders,
    raw_body: bytes,
    now: datetime,
    known_providers: frozenset[str] = frozenset({"sim"}),
    max_skew_seconds: int = MAX_SKEW_SECONDS,
) -> Verified | Rejection:
    """Authenticate a delivery. A callback is trusted by its HMAC and nothing else.

    Not by source IP, not by anything the body claims about itself. The body is
    data written by someone else, so it earns no trust until this passes.
    """
    if headers.provider not in known_providers:
        return Rejection.UNKNOWN_PROVIDER

    skew = abs((now - headers.delivery_timestamp).total_seconds())
    if skew > max_skew_seconds:
        return Rejection.SKEW_TOO_LARGE

    expected = sign(
        secret=secret,
        delivery_timestamp=_timestamp_text(headers.delivery_timestamp),
        event_id=headers.event_id,
        raw_body=raw_body,
    )
    # Constant time: a timing side channel here would leak the secret one byte
    # at a time to anyone willing to send enough callbacks.
    if not hmac.compare_digest(expected, headers.signature):
        return Rejection.BAD_SIGNATURE

    return Verified(
        provider=headers.provider,
        event_id=headers.event_id,
        body_hash=body_hash(raw_body),
        delivery_timestamp=headers.delivery_timestamp,
    )


def _timestamp_text(moment: datetime) -> str:
    """RFC3339 UTC with milliseconds, matching the canonical timestamp format."""
    from datetime import UTC

    utc_moment = moment.astimezone(UTC)
    millis = utc_moment.microsecond // 1000
    return f"{utc_moment.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def disposition_of(
    *,
    verified: Verified,
    existing_body_hash: str | None,
    lookup: ProviderLookup | None,
    body: CallbackBody,
) -> Disposition:
    """Decide what to do with an authenticated delivery.

    Four outcomes, and only one of them writes a fact:

    - **duplicate** -- same event, same bytes. A redelivery. Acknowledge, change
      nothing.
    - **conflicted** -- same event id, different bytes. Someone is replaying an
      id with a changed body. Never applied.
    - **quarantined** -- we cannot match it to a payment we made, or it claims
      terms we never approved. A callback asserting a different amount is exactly
      the thing that must not quietly become truth.
    - **applied** -- it is about our payment, and it says what we expect.
    """
    if existing_body_hash is not None:
        if existing_body_hash == verified.body_hash:
            return Disposition.DUPLICATE
        return Disposition.CONFLICTED

    if lookup is None:
        return Disposition.QUARANTINED

    if body.kind is FactKind.PAYMENT:
        matches = lookup.matches(
            seller_id=body.seller_id,
            amount=Money(amount_paise=body.amount_paise, currency=body.currency),
            currency=body.currency,
        )
        if not matches:
            return Disposition.QUARANTINED

    return Disposition.APPLIED


__all__ = [
    "CONTRACT_VERSION",
    "HEADER_EVENT_ID",
    "HEADER_PROVIDER",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "MAX_SKEW_SECONDS",
    "CallbackBody",
    "CallbackHeaders",
    "Disposition",
    "FactKind",
    "Rejection",
    "Verified",
    "disposition_of",
    "sign",
    "signing_input",
    "verify",
]
