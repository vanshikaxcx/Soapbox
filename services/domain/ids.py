"""Opaque identifiers, the result-set mode, and the shared model base (WP-02).

IDs are constrained to ``^[A-Za-z0-9_-]{8,64}$`` so that canonical JSON and the
hashes built over it stay stable, and so no identifier can carry a slash, a
space or a control character into a signing input.

Timestamps are timezone-aware UTC everywhere. A naive datetime is rejected at
construction rather than silently assumed to be UTC -- the assumption is how
expiry bugs get written.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"
_ID_RE = re.compile(ID_PATTERN)

#: An opaque identifier. Callers generate these; the domain never invents one.
Id = Annotated[str, Field(pattern=ID_PATTERN)]

#: A lowercase hex SHA-256 digest.
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def is_valid_id(value: str) -> bool:
    return bool(_ID_RE.fullmatch(value))


class Mode(StrEnum):
    """Whether a result set came from live merchants or from fixtures.

    Live and fixture data are never combined, never ranked together, and the
    mode is bound into the quote hash so a fixture quote can never be presented
    as a live one.
    """

    LIVE = "live"
    FIXTURE = "fixture"


class Record(BaseModel):
    """Base for every domain record.

    Strict: no coercion, so ``"100"`` is not an int and ``1.0`` is not an int.
    Frozen: a "mutation" is a pure function returning a new record, which makes
    accidental in-place state change impossible.
    Extra forbidden: an unexpected field is a bug, not something to ignore.
    """

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        validate_assignment=True,
    )


def utc(value: datetime) -> datetime:
    """Validate that a datetime is timezone-aware, and normalise it to UTC."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware; naive datetimes are rejected")
    return value.astimezone(UTC)


class Timestamped(Record):
    """Mixin validator for models carrying aware-UTC datetimes."""

    @field_validator("*", mode="after")
    @classmethod
    def _require_aware_utc(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return utc(value)
        return value


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Digest",
    "ID_PATTERN",
    "Id",
    "Mode",
    "Record",
    "Timestamped",
    "is_valid_id",
    "utc",
]
