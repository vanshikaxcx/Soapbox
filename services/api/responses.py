"""Domain errors to HTTP, in one place (WP-08, WP-09).

The mapping is a table, not a chain of ``if`` statements in each handler, because
every handler has to agree on it and P1 keys different copy off each code.

Two choices worth stating:

- An inaccessible record is **404, never 403**. Telling someone a purchase exists
  but is not theirs still tells them it exists.
- A lost race that resolved into the winner's result is **200**, not 409. The
  caller asked for an attempt and there is one; that it was not the call that
  created it is our bookkeeping, not their problem.
"""

from __future__ import annotations

from typing import Any

from services.api import envelope
from services.application.ports import ConditionFailed
from services.application.purchase import NotFound
from services.domain.errors import (
    ApprovalAlreadyConsumed,
    ApprovalExpired,
    AttemptBlockedByExposure,
    DiffHashMismatch,
    DiffNotAccepted,
    DomainError,
    IdempotencyPayloadMismatch,
    IllegalTransition,
    InvalidRecord,
    PaymentKeyConflict,
    PreparationExpired,
    PurchaseAlreadyClaimed,
    QuoteExpired,
    QuoteHashMismatch,
    QuoteNotConstructible,
    VersionConflict,
)

#: Error type -> HTTP status. Anything absent is a 500, deliberately: an
#: unmapped error is a hole in this table, not something to guess a code for.
STATUS: dict[type, int] = {
    NotFound: 404,
    VersionConflict: 409,
    IdempotencyPayloadMismatch: 409,
    DiffHashMismatch: 409,
    DiffNotAccepted: 409,
    QuoteHashMismatch: 409,
    PurchaseAlreadyClaimed: 409,
    AttemptBlockedByExposure: 409,
    PaymentKeyConflict: 409,
    IllegalTransition: 409,
    ConditionFailed: 409,
    QuoteExpired: 410,
    ApprovalExpired: 410,
    PreparationExpired: 410,
    QuoteNotConstructible: 422,
    InvalidRecord: 422,
    ApprovalAlreadyConsumed: 409,
}


class Response:
    """A status and a body. No framework type, so this stays testable alone."""

    __slots__ = ("status", "body")

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Response({self.status}, {self.body})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Response) and other.status == self.status and other.body == self.body
        )


def status_for(error: DomainError) -> int:
    return STATUS.get(type(error), 500)


def ok(data: Any, request_id: str, status: int = 200) -> Response:
    # P4's envelope helper, not a second set of our own: WP-00 established it
    # and every handler in the repo uses the same one.
    return Response(status, envelope.success(_plain(data), request_id))


def accepted(*, job_id: str | None, resource_id: str, request_id: str) -> Response:
    """202 after the durable commit, never before it."""
    return Response(
        202,
        envelope.success(
            {
                "job_id": job_id,
                "resource_id": resource_id,
                "status_url": f"/jobs/{job_id}" if job_id else None,
            },
            request_id,
        ),
    )


def failed(error: DomainError, request_id: str) -> Response:
    """Structured, safe fields only -- no prose, because P1 owns the wording."""
    return Response(
        status_for(error),
        envelope.error(
            code=error.code,
            message=error.code.replace("_", " "),
            details=_error_details(error),
            request_id=request_id,
        ),
    )


def _error_details(error: DomainError) -> dict[str, Any]:
    fields = getattr(error, "__slots__", ()) or ()
    return {name: _plain(getattr(error, name)) for name in fields if name != "code"}


def _plain(value: Any) -> Any:
    """Serialise without leaking model internals or non-JSON types."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


__all__ = ["STATUS", "Response", "accepted", "failed", "ok", "status_for"]
