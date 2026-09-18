"""Canonical JSON and hashing (WP-02), scheme ``pp-canon-v1``.

Rules:

1. UTF-8, no insignificant whitespace, no trailing newline.
2. Object keys sorted by Unicode code point.
3. Strings NFC-normalised.
4. Integers only. A float in a hashed payload *raises* -- it is a programming
   error, since money is already integer paise.
5. Every declared field is present, with an explicit null for an absent value.
   Nothing is omitted. Omitting nulls is the usual convention and a collision
   bug here: ``{"delivery_charge": null}`` and ``{}`` would hash identically, so
   "we don't know the delivery fee" and "there is no delivery fee" would be
   indistinguishable inside a signature.
6. Booleans lowercase; no NaN or Infinity.
7. Timestamps are RFC3339 UTC with exactly three fractional digits. Fixed
   precision, because a value that round-trips through storage which truncates
   microseconds must still hash the same.

Every digest is domain-separated by a tag, so one hash kind can never be
replayed as another.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

CANON_SCHEME = "pp-canon-v1"

# Domain-separation tags. Each hash kind gets its own; never reuse one.
TAG_QUOTE = "proofpath.quote.v1"
TAG_DIFF = "proofpath.diff.v1"
TAG_LINES = "proofpath.lines.v1"
TAG_IDEMPOTENCY = "proofpath.idem.v1"
TAG_APPROVAL_ID = "proofpath.approval_id.v1"
TAG_PAYMENT_KEY = "proofpath.payment_key.v1"
TAG_PAYMENT_REQUEST = "proofpath.payment_request.v1"
TAG_ORDER_KEY = "proofpath.order_key.v1"
TAG_BODY = "proofpath.body.v1"

ALL_TAGS = (
    TAG_QUOTE,
    TAG_DIFF,
    TAG_LINES,
    TAG_IDEMPOTENCY,
    TAG_APPROVAL_ID,
    TAG_PAYMENT_KEY,
    TAG_PAYMENT_REQUEST,
    TAG_ORDER_KEY,
    TAG_BODY,
)


class CanonicalEncodingError(TypeError):
    """Raised for a value that must never reach a signing input."""


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise CanonicalEncodingError(
            "naive datetime cannot be canonicalised; timestamps must be aware UTC"
        )
    moment = value.astimezone(UTC)
    millis = moment.microsecond // 1000
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def _prepare(value: Any) -> Any:
    """Convert a domain value into JSON primitives, refusing anything ambiguous."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalEncodingError(
            "float in a hashed payload; money is integer paise and rates are Fractions"
        )
    if isinstance(value, Decimal):
        raise CanonicalEncodingError("Decimal in a hashed payload; use integer paise")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, Enum):
        return _prepare(value.value)
    if isinstance(value, BaseModel):
        # model_dump keeps every declared field, including explicit Nones,
        # which is exactly rule 5.
        return _prepare(value.model_dump())
    if isinstance(value, (list, tuple)):
        return [_prepare(item) for item in value]
    if isinstance(value, dict):
        prepared: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEncodingError(f"object key must be a string, got {type(key)!r}")
            prepared[unicodedata.normalize("NFC", key)] = _prepare(item)
        return prepared
    raise CanonicalEncodingError(f"unsupported type in hashed payload: {type(value)!r}")


def canonical_json(value: Any) -> bytes:
    """Encode a value as canonical UTF-8 JSON bytes."""
    return json.dumps(
        _prepare(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(tag: str, value: Any) -> str:
    """Lowercase hex SHA-256 over ``tag \\n canonical_json(value)``."""
    if tag not in ALL_TAGS:
        raise CanonicalEncodingError(f"unknown domain-separation tag: {tag!r}")
    payload = tag.encode("utf-8") + b"\n" + canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def body_hash(raw_body: bytes) -> str:
    """Digest of a raw request body, byte for byte as received.

    Used for callback deduplication. It hashes the *bytes*, never a re-serialised
    object, because a JSON round-trip can reorder keys and change whitespace.
    """
    if not isinstance(raw_body, (bytes, bytearray)):
        raise CanonicalEncodingError("body hash requires raw bytes")
    return hashlib.sha256(TAG_BODY.encode("utf-8") + b"\n" + bytes(raw_body)).hexdigest()


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "ALL_TAGS",
    "CANON_SCHEME",
    "CanonicalEncodingError",
    "TAG_APPROVAL_ID",
    "TAG_BODY",
    "TAG_DIFF",
    "TAG_IDEMPOTENCY",
    "TAG_LINES",
    "TAG_ORDER_KEY",
    "TAG_PAYMENT_KEY",
    "TAG_PAYMENT_REQUEST",
    "TAG_QUOTE",
    "body_hash",
    "canonical_json",
    "digest",
]
