"""State machines (WP-02 acceptance criteria 10, 11).

The important test here is the exhaustive one: every machine's full cartesian
product of states and events is enumerated, and everything not in the table must
be rejected. A new state cannot be added without a deliberate table entry.
"""

from __future__ import annotations

import itertools

import pytest

from services.domain.errors import IllegalTransition
from services.domain.transitions import (
    MACHINES,
    ApprovalEvent,
    ApprovalState,
    CaseEvent,
    CaseState,
    ClaimEvent,
    ClaimState,
    DispatchEvent,
    DispatchState,
    JobEvent,
    JobState,
    OrderState,
    PaymentEvent,
    PaymentState,
    RefundState,
    apply,
    is_terminal,
)

MACHINE_NAMES = sorted(MACHINES)


# -- the exhaustive guard --------------------------------------------------


@pytest.mark.parametrize("machine", MACHINE_NAMES)
def test_every_pair_outside_the_table_is_rejected(machine: str) -> None:
    states, events, table, _ = MACHINES[machine]
    for state, event in itertools.product(states, events):
        result = apply(machine, state, event)
        if (state, event) in table:
            assert result == table[(state, event)]
        else:
            assert isinstance(result, IllegalTransition), (
                f"{machine}: ({state}, {event}) was accepted but is not in the table"
            )
            assert result.machine == machine


@pytest.mark.parametrize("machine", MACHINE_NAMES)
def test_every_table_target_is_a_declared_state(machine: str) -> None:
    states, _, table, _ = MACHINES[machine]
    for target in table.values():
        assert target in set(states)


@pytest.mark.parametrize("machine", MACHINE_NAMES)
def test_terminal_states_have_no_outgoing_edges(machine: str) -> None:
    """Except where a deliberate revival edge exists, which we enumerate."""
    _, _, table, terminals = MACHINES[machine]
    allowed_revivals = {
        # Retry is the only way out of a failed job, and the caller must bump
        # the run generation when taking it.
        ("job", JobState.FAILED, JobEvent.RETRY),
    }
    for (state, event), _ in table.items():
        if state in terminals:
            assert (machine, state, event) in allowed_revivals, (
                f"{machine}: terminal {state} has an unexpected edge on {event}"
            )


# -- payment ---------------------------------------------------------------


def test_payment_happy_path() -> None:
    assert apply("payment", PaymentState.NOT_STARTED, PaymentEvent.CLAIM) is PaymentState.CLAIMED
    assert (
        apply("payment", PaymentState.CLAIMED, PaymentEvent.REPORT_PENDING) is PaymentState.PENDING
    )
    assert (
        apply("payment", PaymentState.PENDING, PaymentEvent.REPORT_SUCCEEDED)
        is PaymentState.SUCCEEDED
    )


def test_pending_and_unknown_interconvert() -> None:
    assert (
        apply("payment", PaymentState.PENDING, PaymentEvent.REPORT_UNKNOWN) is PaymentState.UNKNOWN
    )
    assert (
        apply("payment", PaymentState.UNKNOWN, PaymentEvent.REPORT_PENDING) is PaymentState.PENDING
    )


@pytest.mark.parametrize("event", list(PaymentEvent))
def test_nothing_leaves_a_succeeded_payment(event: PaymentEvent) -> None:
    assert isinstance(apply("payment", PaymentState.SUCCEEDED, event), IllegalTransition)


@pytest.mark.parametrize("event", list(PaymentEvent))
def test_nothing_leaves_a_failed_payment(event: PaymentEvent) -> None:
    assert isinstance(apply("payment", PaymentState.FAILED, event), IllegalTransition)


def test_a_payment_cannot_be_claimed_twice() -> None:
    assert isinstance(apply("payment", PaymentState.CLAIMED, PaymentEvent.CLAIM), IllegalTransition)


# -- dispatch: the marker that makes ambiguity safe ------------------------


def test_dispatch_goes_ready_to_started_or_expired_but_never_back() -> None:
    assert apply("dispatch", DispatchState.READY, DispatchEvent.START) is DispatchState.STARTED
    assert (
        apply("dispatch", DispatchState.READY, DispatchEvent.EXPIRE) is DispatchState.EXPIRED_UNSENT
    )


@pytest.mark.parametrize("event", list(DispatchEvent))
def test_nothing_escapes_started(event: DispatchEvent) -> None:
    """Once a provider has been called, expiry cannot undo it."""
    assert isinstance(apply("dispatch", DispatchState.STARTED, event), IllegalTransition)


@pytest.mark.parametrize("event", list(DispatchEvent))
def test_nothing_escapes_expired_unsent(event: DispatchEvent) -> None:
    assert isinstance(apply("dispatch", DispatchState.EXPIRED_UNSENT, event), IllegalTransition)


def test_an_expired_dispatch_cannot_later_start() -> None:
    assert isinstance(
        apply("dispatch", DispatchState.EXPIRED_UNSENT, DispatchEvent.START), IllegalTransition
    )


# -- approval is one-shot --------------------------------------------------


@pytest.mark.parametrize("event", list(ApprovalEvent))
def test_a_consumed_approval_is_final(event: ApprovalEvent) -> None:
    assert isinstance(apply("approval", ApprovalState.CONSUMED, event), IllegalTransition)


def test_an_approval_can_be_consumed_expired_or_cancelled_once() -> None:
    for event, expected in [
        (ApprovalEvent.CONSUME, ApprovalState.CONSUMED),
        (ApprovalEvent.EXPIRE, ApprovalState.EXPIRED),
        (ApprovalEvent.CANCEL, ApprovalState.CANCELLED),
    ]:
        assert apply("approval", ApprovalState.ISSUED, event) is expected


# -- claim can be re-taken after a release --------------------------------


def test_a_released_purchase_can_be_claimed_again() -> None:
    """This is what happens after expired_unsent, when a fresh quote is approved."""
    assert apply("claim", ClaimState.RELEASED, ClaimEvent.CLAIM) is ClaimState.CLAIMED


def test_a_claimed_purchase_cannot_be_claimed_again() -> None:
    assert isinstance(apply("claim", ClaimState.CLAIMED, ClaimEvent.CLAIM), IllegalTransition)


# -- job: failure is sticky until an authorised retry ----------------------


def test_a_failed_job_only_moves_on_retry() -> None:
    assert apply("job", JobState.FAILED, JobEvent.RETRY) is JobState.QUEUED
    for event in (JobEvent.START, JobEvent.SUCCEED, JobEvent.FAIL):
        assert isinstance(apply("job", JobState.FAILED, event), IllegalTransition)


def test_a_succeeded_job_is_final() -> None:
    for event in JobEvent:
        assert isinstance(apply("job", JobState.SUCCEEDED, event), IllegalTransition)


# -- case ------------------------------------------------------------------


def test_a_resolved_case_can_be_reopened_by_new_evidence() -> None:
    assert apply("case", CaseState.RESOLVED, CaseEvent.REOPEN) is CaseState.OPEN


def test_a_closed_case_is_final() -> None:
    for event in CaseEvent:
        assert isinstance(apply("case", CaseState.CLOSED, event), IllegalTransition)


# -- terminal sets ---------------------------------------------------------


def test_terminal_sets_are_what_the_spec_says() -> None:
    assert is_terminal("payment", PaymentState.SUCCEEDED)
    assert is_terminal("payment", PaymentState.FAILED)
    assert not is_terminal("payment", PaymentState.UNKNOWN)
    assert not is_terminal("payment", PaymentState.PENDING)
    assert is_terminal("order", OrderState.CONFIRMED)
    assert not is_terminal("order", OrderState.UNKNOWN)
    assert is_terminal("refund", RefundState.COMPLETED)
    assert not is_terminal("refund", RefundState.UNKNOWN)
