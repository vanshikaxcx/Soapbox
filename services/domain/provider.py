"""Provider facts and the rules for applying them (WP-02).

Three rules, in strict order:

1. **Terminal is sticky.** A non-terminal fact against a terminal state is
   ignored. This is what makes "an old pending callback cannot downgrade a
   success" a property of the type rather than a test we hope someone wrote.
2. **Contradictory terminals quarantine.** succeeded -> failed, or the reverse,
   is never applied. The provider must be queried and the event quarantined.
3. **Otherwise apply if not older.** Among non-terminal states, apply only when
   the incoming observation is at least as recent as the current one.

Payment, order and refund each carry their own facts and move independently.
None is ever derived from another: a confirmed order does not imply a successful
payment, and a successful payment does not imply an order exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import model_validator

from services.domain.errors import (
    ContradictoryProviderFact,
    FactIgnoredStale,
    IllegalTransition,
)
from services.domain.ids import Timestamped
from services.domain.money import Money
from services.domain.transitions import (
    OrderEvent,
    OrderState,
    PaymentEvent,
    PaymentState,
    RefundEvent,
    RefundState,
    apply,
    is_terminal,
)

# Which event reports each state. Kept next to the machines it drives so a new
# state cannot be added without deciding how it is reported.
_PAYMENT_EVENT: dict[PaymentState, PaymentEvent] = {
    PaymentState.PENDING: PaymentEvent.REPORT_PENDING,
    PaymentState.UNKNOWN: PaymentEvent.REPORT_UNKNOWN,
    PaymentState.SUCCEEDED: PaymentEvent.REPORT_SUCCEEDED,
    PaymentState.FAILED: PaymentEvent.REPORT_FAILED,
}

_ORDER_EVENT: dict[OrderState, OrderEvent] = {
    OrderState.PENDING: OrderEvent.REPORT_PENDING,
    OrderState.UNKNOWN: OrderEvent.REPORT_UNKNOWN,
    OrderState.CONFIRMED: OrderEvent.REPORT_CONFIRMED,
    OrderState.FAILED: OrderEvent.REPORT_FAILED,
}

_REFUND_EVENT: dict[RefundState, RefundEvent] = {
    RefundState.PENDING: RefundEvent.REPORT_PENDING,
    RefundState.UNKNOWN: RefundEvent.REPORT_UNKNOWN,
    RefundState.COMPLETED: RefundEvent.REPORT_COMPLETED,
    RefundState.FAILED: RefundEvent.REPORT_FAILED,
}


class Observed(Timestamped):
    """A state as the provider reported it, with when the provider observed it."""

    observed_at: datetime


class PaymentFacts(Observed):
    state: PaymentState
    reference: str | None = None
    amount: Money | None = None
    seller_id: str | None = None

    @model_validator(mode="after")
    def _reported_state_is_reportable(self) -> PaymentFacts:
        if self.state in (PaymentState.NOT_STARTED, PaymentState.CLAIMED):
            raise ValueError("a provider never reports not_started or claimed; those are ours")
        return self


class OrderFacts(Observed):
    state: OrderState
    reference: str | None = None

    @model_validator(mode="after")
    def _reported_state_is_reportable(self) -> OrderFacts:
        if self.state is OrderState.NOT_CREATED:
            raise ValueError("a provider never reports not_created; that is our initial state")
        return self


class RefundFacts(Observed):
    state: RefundState
    reference: str | None = None
    amount: Money | None = None

    @model_validator(mode="after")
    def _reported_state_is_reportable(self) -> RefundFacts:
        if self.state is RefundState.NONE:
            raise ValueError("a provider never reports none; that is our initial state")
        return self


class Current(Timestamped):
    """What we currently believe, and when that belief was observed.

    Timestamped, not Record: a naive datetime here used to pass validation and
    then raise a bare TypeError deep inside fact application -- in the callback
    ingestion path, where an uncaught crash is the worst place for one.
    """

    state: PaymentState | OrderState | RefundState
    observed_at: datetime | None = None


class Applied(Timestamped):
    """A fact that moved, or idempotently re-confirmed, the state."""

    state: PaymentState | OrderState | RefundState
    observed_at: datetime
    changed: bool


ApplyResult = Applied | FactIgnoredStale | ContradictoryProviderFact | IllegalTransition


def _apply(  # noqa: PLR0911
    machine: str,
    current: Current,
    incoming_state: PaymentState | OrderState | RefundState,
    incoming_observed_at: datetime,
    event_map: dict[Any, Any],
) -> ApplyResult:
    current_terminal = is_terminal(machine, current.state)
    incoming_terminal = is_terminal(machine, incoming_state)

    # Rule 1 and 2: a terminal state is only ever re-confirmed, never revised.
    if current_terminal:
        if incoming_state == current.state:
            return Applied(state=current.state, observed_at=incoming_observed_at, changed=False)
        if incoming_terminal:
            return ContradictoryProviderFact(
                machine=machine,
                current=str(current.state),
                incoming=str(incoming_state),
            )
        return FactIgnoredStale(
            machine=machine, current=str(current.state), incoming=str(incoming_state)
        )

    # Rule 3: among non-terminal states, never move backwards in time.
    if current.observed_at is not None and incoming_observed_at < current.observed_at:
        return FactIgnoredStale(
            machine=machine, current=str(current.state), incoming=str(incoming_state)
        )

    event = event_map[incoming_state]
    result = apply(machine, current.state, event)
    if isinstance(result, IllegalTransition):
        return result
    if not isinstance(result, (PaymentState, OrderState, RefundState)):
        # Unreachable: the tables only ever produce these. Stated so the type
        # checker agrees, rather than left as an assumption.
        return IllegalTransition(machine=machine, current=str(current.state), event=str(event))
    return Applied(
        state=result,
        observed_at=incoming_observed_at,
        changed=result != current.state,
    )


def apply_payment_facts(current: Current, incoming: PaymentFacts) -> ApplyResult:
    return _apply("payment", current, incoming.state, incoming.observed_at, _PAYMENT_EVENT)


def apply_order_facts(current: Current, incoming: OrderFacts) -> ApplyResult:
    return _apply("order", current, incoming.state, incoming.observed_at, _ORDER_EVENT)


def apply_refund_facts(current: Current, incoming: RefundFacts) -> ApplyResult:
    return _apply("refund", current, incoming.state, incoming.observed_at, _REFUND_EVENT)


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "Applied",
    "ApplyResult",
    "Current",
    "Observed",
    "OrderFacts",
    "PaymentFacts",
    "RefundFacts",
    "apply_order_facts",
    "apply_payment_facts",
    "apply_refund_facts",
]
