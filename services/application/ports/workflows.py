"""The workflow engine, as the controller needs it (WP-07).

Two calls, and the shape of both is decided by one rule from the spec: **a
duplicate delivery must produce one run, and the thing that guarantees it is the
execution name, not a check the controller might forget.** Starting a run the
engine already has is therefore a success. ``StartedExecution.started_new_run``
says which of the two happened, so a caller that wants to count runs can, while
a caller that just wants the run does not have to care.

``status`` returns ``None`` when the engine has no record of the execution, and
that is deliberately not an ``ExecutionState`` member. "The engine has never
heard of this" and "the engine says it failed" lead to opposite actions, and a
single unknown-shaped value is how they get confused. Repair treats ``None`` as
"keep waiting"; it is the one answer that must never become a job failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ExecutionState(StrEnum):
    """What the engine says became of a run.

    ``TIMED_OUT`` and ``ABORTED`` are kept apart from ``FAILED`` because they
    have different operators behind them: one is the workflow's own deadline,
    one is a human, and one is the work itself. An operator reading a stopped
    job should not have to guess which.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"


#: The states from which nothing more will happen without a new execution.
TERMINAL_STATES = frozenset(
    {
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.TIMED_OUT,
        ExecutionState.ABORTED,
    }
)


@dataclass(frozen=True, slots=True)
class StartedExecution:
    """The run a start resolved to, new or not."""

    run_id: str
    execution_ref: str
    #: ``False`` when the engine already had this name. Not an error: that
    #: collision *is* the duplicate-start suppression this design relies on.
    started_new_run: bool


@dataclass(frozen=True, slots=True)
class ExecutionStatus:
    """What the engine currently reports for one execution."""

    run_id: str
    state: ExecutionState
    result_ref: str | None = None
    error_code: str | None = None


@runtime_checkable
class WorkflowEngine(Protocol):
    """Step Functions in production."""

    def start(self, *, run_id: str, payload: str) -> StartedExecution:
        """Start ``run_id``, or resolve the execution that already has that name.

        The name is ``job_id-rN`` and only a retry changes it, so re-delivering
        the same event resolves to the same run rather than starting a second.
        """
        ...

    def status(self, *, execution_ref: str) -> ExecutionStatus | None:
        """What the engine says now, or ``None`` if it has no such execution."""
        ...


__all__ = [
    "TERMINAL_STATES",
    "ExecutionState",
    "ExecutionStatus",
    "StartedExecution",
    "WorkflowEngine",
]
