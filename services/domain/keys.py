"""Derived identifiers and hashes (WP-02).

Every key here is a pure function of identities that are fixed when consent is
given. None of them reads a clock, a random source, a retry counter or a job
generation -- which is what makes retry, timeout, crash and workflow restart all
reproduce the same key.

``approval_id`` is derived from the consent itself rather than generated per
request. If it were freshly minted, two concurrent approvals of one quote would
produce two different payment keys, two different provider-lookup rows, and the
uniqueness condition on that row would catch nothing. Deriving it means the same
consent always yields the same key, so a duplicate is caught independently by the
approval condition, the lookup condition and the version compare-and-set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from services.domain.canonical import (
    TAG_APPROVAL_ID,
    TAG_DIFF,
    TAG_IDEMPOTENCY,
    TAG_LINES,
    TAG_ORDER_KEY,
    TAG_PAYMENT_KEY,
    TAG_PAYMENT_REQUEST,
    TAG_QUOTE,
    digest,
)


def approval_id(*, quote_id: str, quote_hash: str, quote_version: int) -> str:
    """Identify consent by what was consented to, not by when it was clicked."""
    return digest(
        TAG_APPROVAL_ID,
        {"quote_id": quote_id, "quote_hash": quote_hash, "quote_version": quote_version},
    )


def payment_key(*, purchase_id: str, approval_id: str) -> str:
    """One approval, one payment key, forever."""
    return digest(
        TAG_PAYMENT_KEY, {"purchase_id": purchase_id, "approval_id": approval_id}
    )


def payment_request_hash(
    *,
    payment_key: str,
    quote_hash: str,
    seller_id: str,
    amount_paise: int,
    currency: str,
    expires_at: datetime,
) -> str:
    """Hash of the exact payment payload, frozen when consent is given.

    Checkout rebuilds the payload before every send and refuses unless it
    reproduces this digest. That is what makes "approved Rs X, submitted Rs Y"
    unreachable from our side, before anything goes out -- the provider's own
    same-key/different-payload conflict is the second line of defence, and it
    only fires after the call has already been made.
    """
    return digest(
        TAG_PAYMENT_REQUEST,
        {
            "payment_key": payment_key,
            "quote_hash": quote_hash,
            "seller_id": seller_id,
            "amount_paise": amount_paise,
            "currency": currency,
            "expires_at": expires_at,
        },
    )


def order_key(*, purchase_id: str, attempt_id: str) -> str:
    """Idempotent order creation for a given attempt."""
    return digest(TAG_ORDER_KEY, {"purchase_id": purchase_id, "attempt_id": attempt_id})


def line_hash(lines: Sequence[Any]) -> str:
    """Stable hash of an exact line set, used to bind a fee assessment to it."""
    return digest(TAG_LINES, list(lines))


def diff_hash(changes: Sequence[Any]) -> str:
    """Hash of the exact change list a shopper is asked to accept."""
    return digest(TAG_DIFF, list(changes))


def idempotency_request_hash(
    *,
    method: str,
    path_template: str,
    path_params: Mapping[str, str],
    owner_id: str,
    body: Any,
) -> str:
    """Hash of a mutation request, for same-key/different-payload detection.

    Headers other than the key itself, timestamps and trace IDs are excluded, so
    a legitimate retry of the same request hashes identically.
    """
    return digest(
        TAG_IDEMPOTENCY,
        {
            "method": method.upper(),
            "path_template": path_template,
            "path_params": dict(path_params),
            "owner_id": owner_id,
            "body": body,
        },
    )


def quote_hash(
    *,
    owner_id: str,
    purchase_id: str,
    purchase_version: int,
    quote_id: str,
    quote_version: int,
    seller_id: str,
    source_merchant_id: str,
    mode: Any,
    lines: Sequence[Any],
    charges: Sequence[Any],
    currency: Any,
    delivery: Any,
    expires_at: datetime,
) -> str:
    """Bind a quote to every term that was shown.

    Keyword-only and fully enumerated on purpose: adding a term to a quote without
    binding it here would be a silent hole, and this signature makes that omission
    a visible edit rather than an oversight.

    ``mode`` is bound so a fixture quote and a live quote with identical numbers
    cannot hash the same.
    """
    return digest(
        TAG_QUOTE,
        {
            "owner_id": owner_id,
            "purchase_id": purchase_id,
            "purchase_version": purchase_version,
            "quote_id": quote_id,
            "quote_version": quote_version,
            "seller_id": seller_id,
            "source_merchant_id": source_merchant_id,
            "mode": mode,
            "lines": list(lines),
            "charges": list(charges),
            "currency": currency,
            "delivery": delivery,
            "expires_at": expires_at,
        },
    )


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "approval_id",
    "diff_hash",
    "idempotency_request_hash",
    "line_hash",
    "order_key",
    "payment_request_hash",
    "payment_key",
    "quote_hash",
]
