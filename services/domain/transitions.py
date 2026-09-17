"""Every state machine in ProofPath, as data (WP-02).

Each machine is one table. A transition absent from its table is rejected with
``IllegalTransition`` -- there is no permissive default, so adding a state to an
enum without adding its edges makes the exhaustive test fail rather than making
the system quietly accept something new.

No handler, workflow, task or simulator may encode a transition of its own. This
module is the single authority, and the tables are exported as data so other
packages can assert they are reading the same ones.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from services.domain.errors import IllegalTransition

# -- states ----------------------------------------------------------------


class PaymentState(StrEnum):
    NOT_STARTED = "not_started"
    CLAIMED = "claimed"
    PENDING = "pending"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OrderState(StrEnum):
    NOT_CREATED = "not_created"
    PENDING = "pending"
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class RefundState(StrEnum):
    NONE = "none"
    PENDING = "pending"
    UNKNOWN = "unknown"
    COMPLETED = "completed"
    FAILED = "failed"


class DispatchState(StrEnum):
    READY = "ready"
    STARTED = "started"
    EXPIRED_UNSENT = "expired_unsent"


class ApprovalState(StrEnum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ClaimState(StrEnum):
    UNCLAIMED = "unclaimed"
    CLAIMED = "claimed"
    RELEASED = "released"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InboxState(StrEnum):
    RECEIVED = "received"
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    CONFLICTED = "conflicted"
    QUARANTINED = "quarantined"


class CaseState(StrEnum):
    OPEN = "open"
    AWAITING_USER = "awaiting_user"
    RESOLVED = "resolved"
    CLOSED = "closed"


# -- events ----------------------------------------------------------------


class PaymentEvent(StrEnum):
    CLAIM = "claim"
    REPORT_PENDING = "report_pending"
    REPORT_UNKNOWN = "report_unknown"
    REPORT_SUCCEEDED = "report_succeeded"
    REPORT_FAILED = "report_failed"


class OrderEvent(StrEnum):
    REPORT_PENDING = "report_pending"
    REPORT_UNKNOWN = "report_unknown"
    REPORT_CONFIRMED = "report_confirmed"
    REPORT_FAILED = "report_failed"


class RefundEvent(StrEnum):
    REPORT_PENDING = "report_pending"
    REPORT_UNKNOWN = "report_unknown"
    REPORT_COMPLETED = "report_completed"
    REPORT_FAILED = "report_failed"


class DispatchEvent(StrEnum):
    START = "start"
    EXPIRE = "expire"


class ApprovalEvent(StrEnum):
    CONSUME = "consume"
    EXPIRE = "expire"
    CANCEL = "cancel"


class ClaimEvent(StrEnum):
    CLAIM = "claim"
    RELEASE = "release"


class JobEvent(StrEnum):
    START = "start"
    SUCCEED = "succeed"
    FAIL = "fail"
    RETRY = "retry"


class InboxEvent(StrEnum):
    APPLY = "apply"
    MARK_DUPLICATE = "mark_duplicate"
    MARK_CONFLICTED = "mark_conflicted"
    QUARANTINE = "quarantine"


class CaseEvent(StrEnum):
    AWAIT_USER = "await_user"
    RESOLVE = "resolve"
    CLOSE = "close"
    REOPEN = "reopen"


# -- tables ----------------------------------------------------------------

PAYMENT_TABLE: Final[dict[tuple[PaymentState, PaymentEvent], PaymentState]] = {
    (PaymentState.NOT_STARTED, PaymentEvent.CLAIM): PaymentState.CLAIMED,
    # From claimed, any provider fact may arrive.
    (PaymentState.CLAIMED, PaymentEvent.REPORT_PENDING): PaymentState.PENDING,
    (PaymentState.CLAIMED, PaymentEvent.REPORT_UNKNOWN): PaymentState.UNKNOWN,
    (PaymentState.CLAIMED, PaymentEvent.REPORT_SUCCEEDED): PaymentState.SUCCEEDED,
    (PaymentState.CLAIMED, PaymentEvent.REPORT_FAILED): PaymentState.FAILED,
    # pending and unknown interconvert freely and both can terminate.
    (PaymentState.PENDING, PaymentEvent.REPORT_PENDING): PaymentState.PENDING,
    (PaymentState.PENDING, PaymentEvent.REPORT_UNKNOWN): PaymentState.UNKNOWN,
    (PaymentState.PENDING, PaymentEvent.REPORT_SUCCEEDED): PaymentState.SUCCEEDED,
    (PaymentState.PENDING, PaymentEvent.REPORT_FAILED): PaymentState.FAILED,
    (PaymentState.UNKNOWN, PaymentEvent.REPORT_PENDING): PaymentState.PENDING,
    (PaymentState.UNKNOWN, PaymentEvent.REPORT_UNKNOWN): PaymentState.UNKNOWN,
    (PaymentState.UNKNOWN, PaymentEvent.REPORT_SUCCEEDED): PaymentState.SUCCEEDED,
    (PaymentState.UNKNOWN, PaymentEvent.REPORT_FAILED): PaymentState.FAILED,
    # succeeded and failed have no outgoing edges at all. That absence is what
    # makes "an old pending cannot downgrade a success" structural.
}

ORDER_TABLE: Final[dict[tuple[OrderState, OrderEvent], OrderState]] = {
    (OrderState.NOT_CREATED, OrderEvent.REPORT_PENDING): OrderState.PENDING,
    (OrderState.NOT_CREATED, OrderEvent.REPORT_UNKNOWN): OrderState.UNKNOWN,
    (OrderState.NOT_CREATED, OrderEvent.REPORT_CONFIRMED): OrderState.CONFIRMED,
    (OrderState.NOT_CREATED, OrderEvent.REPORT_FAILED): OrderState.FAILED,
    (OrderState.PENDING, OrderEvent.REPORT_PENDING): OrderState.PENDING,
    (OrderState.PENDING, OrderEvent.REPORT_UNKNOWN): OrderState.UNKNOWN,
    (OrderState.PENDING, OrderEvent.REPORT_CONFIRMED): OrderState.CONFIRMED,
    (OrderState.PENDING, OrderEvent.REPORT_FAILED): OrderState.FAILED,
    (OrderState.UNKNOWN, OrderEvent.REPORT_PENDING): OrderState.PENDING,
    (OrderState.UNKNOWN, OrderEvent.REPORT_UNKNOWN): OrderState.UNKNOWN,
    (OrderState.UNKNOWN, OrderEvent.REPORT_CONFIRMED): OrderState.CONFIRMED,
    (OrderState.UNKNOWN, OrderEvent.REPORT_FAILED): OrderState.FAILED,
}

REFUND_TABLE: Final[dict[tuple[RefundState, RefundEvent], RefundState]] = {
    # A refund may be first observed in any state: a late callback can report a
    # completed refund we never saw go pending. Rejecting that would discard
    # real provider evidence, so `none` accepts every report.
    (RefundState.NONE, RefundEvent.REPORT_PENDING): RefundState.PENDING,
    (RefundState.NONE, RefundEvent.REPORT_UNKNOWN): RefundState.UNKNOWN,
    (RefundState.NONE, RefundEvent.REPORT_COMPLETED): RefundState.COMPLETED,
    (RefundState.NONE, RefundEvent.REPORT_FAILED): RefundState.FAILED,
    (RefundState.PENDING, RefundEvent.REPORT_PENDING): RefundState.PENDING,
    (RefundState.PENDING, RefundEvent.REPORT_UNKNOWN): RefundState.UNKNOWN,
    (RefundState.PENDING, RefundEvent.REPORT_COMPLETED): RefundState.COMPLETED,
    (RefundState.PENDING, RefundEvent.REPORT_FAILED): RefundState.FAILED,
    (RefundState.UNKNOWN, RefundEvent.REPORT_PENDING): RefundState.PENDING,
    (RefundState.UNKNOWN, RefundEvent.REPORT_UNKNOWN): RefundState.UNKNOWN,
    (RefundState.UNKNOWN, RefundEvent.REPORT_COMPLETED): RefundState.COMPLETED,
    (RefundState.UNKNOWN, RefundEvent.REPORT_FAILED): RefundState.FAILED,
}

DISPATCH_TABLE: Final[dict[tuple[DispatchState, DispatchEvent], DispatchState]] = {
    (DispatchState.READY, DispatchEvent.START): DispatchState.STARTED,
    (DispatchState.READY, DispatchEvent.EXPIRE): DispatchState.EXPIRED_UNSENT,
    # There is deliberately no edge out of STARTED. Once a provider has been
    # called, expiry is irrelevant: only facts decide what happened.
}

APPROVAL_TABLE: Final[dict[tuple[ApprovalState, ApprovalEvent], ApprovalState]] = {
    (ApprovalState.ISSUED, ApprovalEvent.CONSUME): ApprovalState.CONSUMED,
    (ApprovalState.ISSUED, ApprovalEvent.EXPIRE): ApprovalState.EXPIRED,
    (ApprovalState.ISSUED, ApprovalEvent.CANCEL): ApprovalState.CANCELLED,
}

CLAIM_TABLE: Final[dict[tuple[ClaimState, ClaimEvent], ClaimState]] = {
    (ClaimState.UNCLAIMED, ClaimEvent.CLAIM): ClaimState.CLAIMED,
    (ClaimState.CLAIMED, ClaimEvent.RELEASE): ClaimState.RELEASED,
    # A released purchase can be claimed again: that is exactly what happens
    # after expired_unsent, when the shopper approves a fresh quote.
    (ClaimState.RELEASED, ClaimEvent.CLAIM): ClaimState.CLAIMED,
}

JOB_TABLE: Final[dict[tuple[JobState, JobEvent], JobState]] = {
    (JobState.QUEUED, JobEvent.START): JobState.RUNNING,
    (JobState.RUNNING, JobEvent.SUCCEED): JobState.SUCCEEDED,
    (JobState.RUNNING, JobEvent.FAIL): JobState.FAILED,
    # Retry is the only way out of failed, and the caller must increment the run
    # generation when taking it. Duplicate delivery never reaches this edge.
    (JobState.FAILED, JobEvent.RETRY): JobState.QUEUED,
}

INBOX_TABLE: Final[dict[tuple[InboxState, InboxEvent], InboxState]] = {
    (InboxState.RECEIVED, InboxEvent.APPLY): InboxState.APPLIED,
    (InboxState.RECEIVED, InboxEvent.MARK_DUPLICATE): InboxState.DUPLICATE,
    (InboxState.RECEIVED, InboxEvent.MARK_CONFLICTED): InboxState.CONFLICTED,
    (InboxState.RECEIVED, InboxEvent.QUARANTINE): InboxState.QUARANTINED,
}

CASE_TABLE: Final[dict[tuple[CaseState, CaseEvent], CaseState]] = {
    (CaseState.OPEN, CaseEvent.AWAIT_USER): CaseState.AWAITING_USER,
    (CaseState.OPEN, CaseEvent.RESOLVE): CaseState.RESOLVED,
    (CaseState.AWAITING_USER, CaseEvent.AWAIT_USER): CaseState.AWAITING_USER,
    (CaseState.AWAITING_USER, CaseEvent.RESOLVE): CaseState.RESOLVED,
    (CaseState.RESOLVED, CaseEvent.CLOSE): CaseState.CLOSED,
    (CaseState.RESOLVED, CaseEvent.REOPEN): CaseState.OPEN,
}


# -- machine registry ------------------------------------------------------

#: name -> (state enum, event enum, table, terminal states)
MACHINES: Final[
    dict[str, tuple[type[StrEnum], type[StrEnum], dict[Any, Any], frozenset[Any]]]
] = {
    "payment": (
        PaymentState,
        PaymentEvent,
        PAYMENT_TABLE,
        frozenset({PaymentState.SUCCEEDED, PaymentState.FAILED}),
    ),
    "order": (
        OrderState,
        OrderEvent,
        ORDER_TABLE,
        frozenset({OrderState.CONFIRMED, OrderState.FAILED}),
    ),
    "refund": (
        RefundState,
        RefundEvent,
        REFUND_TABLE,
        frozenset({RefundState.COMPLETED, RefundState.FAILED}),
    ),
    "dispatch": (
        DispatchState,
        DispatchEvent,
        DISPATCH_TABLE,
        frozenset({DispatchState.STARTED, DispatchState.EXPIRED_UNSENT}),
    ),
    "approval": (
        ApprovalState,
        ApprovalEvent,
        APPROVAL_TABLE,
        frozenset(
            {ApprovalState.CONSUMED, ApprovalState.EXPIRED, ApprovalState.CANCELLED}
        ),
    ),
    "claim": (ClaimState, ClaimEvent, CLAIM_TABLE, frozenset()),
    "job": (JobState, JobEvent, JOB_TABLE, frozenset({JobState.SUCCEEDED})),
    "inbox": (
        InboxState,
        InboxEvent,
        INBOX_TABLE,
        frozenset(
            {
                InboxState.APPLIED,
                InboxState.DUPLICATE,
                InboxState.CONFLICTED,
                InboxState.QUARANTINED,
            }
        ),
    ),
    "case": (CaseState, CaseEvent, CASE_TABLE, frozenset({CaseState.CLOSED})),
}


class StateMachineMisuse(TypeError):
    """A state or event from the wrong machine. A bug, not a domain outcome.

    Raised rather than returned, on the same principle as the canonical encoder
    raising on a float: an expected conflict is a value a caller handles, but a
    payment state fed to the order machine is a mistake in the code.
    """


def _check(machine: str, current: StrEnum, event: StrEnum | None = None) -> None:
    """Guard against cross-machine confusion.

    ``StrEnum`` members compare and hash equal to any string of the same value,
    so ``OrderState.PENDING == PaymentState.PENDING`` is True and a table lookup
    keyed on one will happily match the other. Without this check the machine
    registry offers no type safety at all: an order state fed to the payment
    machine would silently transition to a payment state. Exact-type comparison
    is deliberate -- ``isinstance`` would not catch it either, since these are
    all subclasses of ``str``.
    """
    states, events, _, _ = MACHINES[machine]
    if type(current) is not states:
        raise StateMachineMisuse(
            f"{machine} machine given {type(current).__name__}.{current}; "
            f"expected a {states.__name__}"
        )
    if event is not None and type(event) is not events:
        raise StateMachineMisuse(
            f"{machine} machine given {type(event).__name__}.{event}; "
            f"expected a {events.__name__}"
        )


def is_terminal(machine: str, state: StrEnum) -> bool:
    _check(machine, state)
    return state in MACHINES[machine][3]


def apply(machine: str, current: StrEnum, event: StrEnum) -> StrEnum | IllegalTransition:
    """The single entry point for every state change in the system."""
    _check(machine, current, event)
    _, _, table, _ = MACHINES[machine]
    result: StrEnum | None = table.get((current, event))
    if result is None:
        return IllegalTransition(
            machine=machine, current=str(current), event=str(event)
        )
    return result


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "APPROVAL_TABLE",
    "StateMachineMisuse",
    "ApprovalEvent",
    "ApprovalState",
    "CASE_TABLE",
    "CLAIM_TABLE",
    "CaseEvent",
    "CaseState",
    "ClaimEvent",
    "ClaimState",
    "DISPATCH_TABLE",
    "DispatchEvent",
    "DispatchState",
    "INBOX_TABLE",
    "InboxEvent",
    "InboxState",
    "JOB_TABLE",
    "JobEvent",
    "JobState",
    "MACHINES",
    "ORDER_TABLE",
    "OrderEvent",
    "OrderState",
    "PAYMENT_TABLE",
    "PaymentEvent",
    "PaymentState",
    "REFUND_TABLE",
    "RefundEvent",
    "RefundState",
    "apply",
    "is_terminal",
]
