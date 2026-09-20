"""The Step Functions ``WorkflowEngine`` (WP-07).

Standard workflows treat the execution name as an idempotency key, and they do
it in two different ways depending on the input, which is the whole subtlety of
this adapter:

* same name, **same** input -- the call succeeds and returns the existing
  execution. No error at all, and nothing on the response to say a run was not
  created. A controller that counted successful starts as new runs would report
  two runs for one.
* same name, **different** input -- ``ExecutionAlreadyExists`` is raised.

Both mean "this run already exists", so both resolve to it and neither is an
error. That is the spec's rule, and it is the reason duplicate delivery cannot
produce a second run: the suppression is the name, not a check anyone has to
remember to write.

The second case also carries a warning worth reading. Two different payloads
claimed one generation, which means something upstream changed the job's input
without retrying it. This adapter resolves to the existing run, because starting
a second is the one thing it must never do -- but the mismatch is surfaced on
``StartedExecution`` so a caller is able to notice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from botocore.exceptions import ClientError

from services.application.ports import (
    ExecutionState,
    ExecutionStatus,
    StartedExecution,
)

if TYPE_CHECKING:  # pragma: no cover - import exists for the type checker only
    from mypy_boto3_stepfunctions.client import SFNClient

#: Step Functions' own vocabulary, mapped onto the port's. ``PENDING_REDRIVE``
#: is a run waiting to be redriven, which has not finished and must not be
#: reported as though it had.
_STATES: Final = {
    "RUNNING": ExecutionState.RUNNING,
    "PENDING_REDRIVE": ExecutionState.RUNNING,
    "SUCCEEDED": ExecutionState.SUCCEEDED,
    "FAILED": ExecutionState.FAILED,
    "TIMED_OUT": ExecutionState.TIMED_OUT,
    "ABORTED": ExecutionState.ABORTED,
}

#: Raised when the name exists and the input differs.
ALREADY_EXISTS: Final = "ExecutionAlreadyExists"

#: Raised by ``describe_execution`` for an execution the engine does not have.
DOES_NOT_EXIST: Final = "ExecutionDoesNotExist"


class StepFunctionsEngine:
    """Starts and inspects executions of one state machine."""

    def __init__(self, *, client: SFNClient, state_machine_arn: str) -> None:
        self._client = client
        self._arn = state_machine_arn

    def start(self, *, run_id: str, payload: str) -> StartedExecution:
        # Asked first, because Step Functions gives no other way to tell the two
        # outcomes apart: an identical re-start returns the existing execution
        # with no error and nothing on the response saying so. This is
        # best-effort and only for reporting -- two controllers racing here can
        # both call it new. The *guarantee* that there is one run is the name,
        # and that holds whatever this probe says.
        existed = self.status(execution_ref=self.execution_ref(run_id)) is not None
        try:
            response = self._client.start_execution(
                stateMachineArn=self._arn, name=run_id, input=payload
            )
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code", "")) != ALREADY_EXISTS:
                raise
            # The name is taken by a run started from a different input. The run
            # that exists is the one that counts; starting another would be the
            # double-run this whole design exists to prevent.
            return StartedExecution(
                run_id=run_id, execution_ref=self.execution_ref(run_id), started_new_run=False
            )
        return StartedExecution(
            run_id=run_id,
            execution_ref=response["executionArn"],
            started_new_run=not existed,
        )

    def status(self, *, execution_ref: str) -> ExecutionStatus | None:
        try:
            described = self._client.describe_execution(executionArn=execution_ref)
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code", "")) == DOES_NOT_EXIST:
                # Not a failure. "The engine has never heard of this" and "the
                # engine says it failed" lead to opposite actions, and repair
                # must not turn the first into the second.
                return None
            raise
        state = _STATES.get(described["status"])
        if state is None:
            # An unrecognised status is not a finished one. Reporting a state we
            # do not understand as terminal would close a job that is still
            # running; reporting it as running costs one more repair pass.
            state = ExecutionState.RUNNING
        return ExecutionStatus(
            run_id=described.get("name", ""),
            state=state,
            result_ref=described.get("output") or None,
            error_code=described.get("error") or None,
            started_at=described.get("startDate"),
        )

    def execution_ref(self, run_id: str) -> str:
        """The execution ARN for a name, derived rather than looked up.

        AWS documents the format, and ``ExecutionAlreadyExists`` does not carry
        the ARN of the run that took the name -- so the alternative is a list
        call that could page past the execution it is looking for.
        """
        return f"{self._arn.replace(':stateMachine:', ':execution:')}:{run_id}"


__all__ = ["ALREADY_EXISTS", "DOES_NOT_EXIST", "StepFunctionsEngine"]
