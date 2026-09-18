"""One suite, two engines: the fake and Step Functions must be interchangeable.

The same reasoning as the ``StateStore`` conformance suite. The controller's
guarantee -- one delivery, one run -- is proved against a fake, and that proof is
only evidence about production if the two engines answer the same way. So every
test here is written against the port, and each runs twice.

Two things only a backend can provide are handed over by the fixture rather than
reached for in a test: a reference to an execution that does not exist, and a way
to drive a run to a terminal state. Everything else goes through ``start`` and
``status``.

``moto`` keeps a started execution ``RUNNING`` rather than simulating the state
machine, which is exactly the shape repair cares about; ``stop_execution`` gives
one real terminal state. The remaining terminal mappings cannot be reached
through moto at all, so they are checked against injected responses in the
adapter-only section at the bottom.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from services.adapters.stepfunctions_engine import DOES_NOT_EXIST, StepFunctionsEngine
from services.application.fakes import RecordingWorkflowEngine
from services.application.ports import ExecutionState, WorkflowEngine

REGION = "ap-south-1"
MACHINE = "proofpath-jobs"
RUN = "job-0000001-r1"
OTHER_RUN = "job-0000001-r2"
PAYLOAD = json.dumps({"job_id": "job-0000001", "generation": 1}, sort_keys=True)
DEFINITION = json.dumps({"StartAt": "Done", "States": {"Done": {"Type": "Pass", "End": True}}})


@dataclass
class Harness:
    """An engine, plus the three things only its own backend can do."""

    engine: WorkflowEngine
    unknown_ref: str
    stop: Any
    #: How many executions the engine actually holds. That count is the point of
    #: the whole port, so it is counted rather than inferred from what ``start``
    #: happened to return.
    count_runs: Any


@contextmanager
def fake() -> Iterator[Harness]:
    engine = RecordingWorkflowEngine()

    def stop(execution_ref: str) -> None:
        engine.finish(engine.run_id_of(execution_ref), ExecutionState.ABORTED)

    yield Harness(
        engine=engine,
        unknown_ref="arn:fake:execution:job-0000009-r9",
        stop=stop,
        count_runs=engine.runs,
    )


@contextmanager
def step_functions() -> Iterator[Harness]:
    with mock_aws():
        credentials = {
            "region_name": REGION,
            "aws_access_key_id": "conformance",
            "aws_secret_access_key": "conformance",
            "aws_session_token": "conformance",
        }
        role = boto3.client("iam", **credentials).create_role(  # type: ignore[call-overload]
            RoleName="proofpath-jobs", AssumeRolePolicyDocument="{}"
        )["Role"]["Arn"]
        client = boto3.client("stepfunctions", **credentials)  # type: ignore[call-overload]
        arn = client.create_state_machine(name=MACHINE, definition=DEFINITION, roleArn=role)[
            "stateMachineArn"
        ]
        engine = StepFunctionsEngine(client=client, state_machine_arn=arn)

        def stop(execution_ref: str) -> None:
            client.stop_execution(executionArn=execution_ref, error="OperatorStopped")

        def count_runs() -> int:
            return len(client.list_executions(stateMachineArn=arn)["executions"])

        yield Harness(
            engine=engine,
            unknown_ref=engine.execution_ref("job-0000009-r9"),
            stop=stop,
            count_runs=count_runs,
        )


@pytest.fixture(params=["fake", "stepfunctions"])
def harness(request: pytest.FixtureRequest) -> Iterator[Harness]:
    with fake() if request.param == "fake" else step_functions() as built:
        yield built


def test_both_engines_satisfy_the_port(harness: Harness) -> None:
    assert isinstance(harness.engine, WorkflowEngine)


def test_starting_a_run_reports_it_as_new(harness: Harness) -> None:
    started = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    assert started.run_id == RUN
    assert started.started_new_run is True
    assert started.execution_ref


def test_a_started_run_is_running(harness: Harness) -> None:
    started = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    status = harness.engine.status(execution_ref=started.execution_ref)
    assert status is not None
    assert status.state is ExecutionState.RUNNING


def test_starting_the_same_name_again_resolves_rather_than_duplicating(
    harness: Harness,
) -> None:
    """The duplicate-start suppression, and the reason it cannot be forgotten.

    Nothing here checks whether the run exists first. The name collides, and the
    collision is the answer.
    """
    first = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    second = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    assert second.execution_ref == first.execution_ref
    assert second.started_new_run is False
    assert harness.count_runs() == 1


def test_starting_the_same_name_with_a_different_payload_still_resolves(
    harness: Harness,
) -> None:
    """Step Functions raises ``ExecutionAlreadyExists`` for this case and returns
    quietly for the identical one. Both mean the run exists, so both resolve to
    it: starting a second run is the one thing that must never happen.
    """
    first = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    second = harness.engine.start(run_id=RUN, payload='{"different":true}')
    assert second.execution_ref == first.execution_ref
    assert second.started_new_run is False
    assert harness.count_runs() == 1


def test_a_different_name_is_a_different_run(harness: Harness) -> None:
    """Which is what makes an incremented generation a genuinely new execution."""
    first = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    second = harness.engine.start(run_id=OTHER_RUN, payload=PAYLOAD)
    assert second.execution_ref != first.execution_ref
    assert second.started_new_run is True
    assert harness.count_runs() == 2


def test_many_deliveries_of_one_name_leave_exactly_one_run(harness: Harness) -> None:
    """Acceptance criterion 6, as far as it can be proved without the cloud."""
    for _ in range(5):
        harness.engine.start(run_id=RUN, payload=PAYLOAD)
    assert harness.count_runs() == 1


def test_an_execution_the_engine_does_not_have_is_none_not_a_failure(
    harness: Harness,
) -> None:
    """The single most important answer in this port.

    ``None`` and "failed" lead to opposite actions in repair, so an engine that
    reported an unknown execution as failed would close jobs that are running.
    """
    assert harness.engine.status(execution_ref=harness.unknown_ref) is None


def test_a_stopped_run_reports_a_terminal_state(harness: Harness) -> None:
    started = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    harness.stop(started.execution_ref)
    status = harness.engine.status(execution_ref=started.execution_ref)
    assert status is not None
    assert status.state is ExecutionState.ABORTED


def test_a_terminal_run_does_not_become_running_again(harness: Harness) -> None:
    started = harness.engine.start(run_id=RUN, payload=PAYLOAD)
    harness.stop(started.execution_ref)
    for _ in range(3):
        status = harness.engine.status(execution_ref=started.execution_ref)
        assert status is not None
        assert status.state is not ExecutionState.RUNNING


# -- how the adapter reads a status -----------------------------------------
#
# Adapter-only: moto keeps executions running, so these mappings have no path
# through it. They are checked against the vocabulary AWS documents, because an
# unmapped status is how a finished job stays open or an open one gets closed.


def described(status: str, **extra: str) -> dict[str, Any]:
    return {"name": RUN, "status": status, **extra}


def on_a_stub() -> tuple[StepFunctionsEngine, MagicMock]:
    """The adapter over a client that answers whatever a test needs.

    Built directly rather than by patching a real one's insides: the client is a
    constructor argument precisely so that it can be replaced.
    """
    client = MagicMock()
    arn = f"arn:aws:states:{REGION}:123456789012:stateMachine:{MACHINE}"
    return StepFunctionsEngine(client=client, state_machine_arn=arn), client


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("RUNNING", ExecutionState.RUNNING),
        ("SUCCEEDED", ExecutionState.SUCCEEDED),
        ("FAILED", ExecutionState.FAILED),
        ("TIMED_OUT", ExecutionState.TIMED_OUT),
        ("ABORTED", ExecutionState.ABORTED),
    ],
)
def test_every_documented_status_maps(reported: str, expected: ExecutionState) -> None:
    engine, client = on_a_stub()
    client.describe_execution.return_value = described(reported)
    status = engine.status(execution_ref="arn:whatever")
    assert status is not None
    assert status.state is expected


def test_a_run_waiting_to_be_redriven_has_not_finished() -> None:
    """``PENDING_REDRIVE`` is not terminal, and reporting it as one would close
    a job that is about to run again.
    """
    engine, client = on_a_stub()
    client.describe_execution.return_value = described("PENDING_REDRIVE")
    status = engine.status(execution_ref="arn:whatever")
    assert status is not None
    assert status.state is ExecutionState.RUNNING


def test_a_status_we_do_not_recognise_is_treated_as_still_running() -> None:
    """AWS can add one. Guessing "finished" closes a live job; guessing "running"
    costs one more repair pass, so the cheap mistake is the one to make.
    """
    engine, client = on_a_stub()
    client.describe_execution.return_value = described("SOMETHING_NEW")
    status = engine.status(execution_ref="arn:whatever")
    assert status is not None
    assert status.state is ExecutionState.RUNNING


def test_the_engines_own_error_and_output_are_carried_through() -> None:
    engine, client = on_a_stub()
    client.describe_execution.return_value = described(
        "FAILED", error="States.TaskFailed", output='{"detail":1}'
    )
    status = engine.status(execution_ref="arn:whatever")
    assert status is not None
    assert status.error_code == "States.TaskFailed"
    assert status.result_ref == '{"detail":1}'


def test_a_fault_that_is_not_a_missing_execution_is_raised() -> None:
    """Only ``ExecutionDoesNotExist`` means "no such run". Everything else is a
    fault, and swallowing it would report an unknown run for an outage.
    """
    engine, client = on_a_stub()
    client.describe_execution.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException"}}, "DescribeExecution"
    )
    with pytest.raises(ClientError):
        engine.status(execution_ref="arn:whatever")


def test_a_start_fault_that_is_not_a_name_collision_is_raised() -> None:
    engine, client = on_a_stub()
    client.describe_execution.side_effect = ClientError(
        {"Error": {"Code": DOES_NOT_EXIST}}, "DescribeExecution"
    )
    client.start_execution.side_effect = ClientError(
        {"Error": {"Code": "StateMachineDoesNotExist"}}, "StartExecution"
    )
    with pytest.raises(ClientError):
        engine.start(run_id=RUN, payload=PAYLOAD)


def test_the_execution_reference_follows_the_documented_arn_format() -> None:
    """Derived rather than looked up, because ``ExecutionAlreadyExists`` does not
    carry the ARN of the run that took the name. Pinned so a change to the
    format is a failing test rather than a silent lookup of nothing.
    """
    with step_functions() as harness:
        engine = harness.engine
        assert isinstance(engine, StepFunctionsEngine)
        started = engine.start(run_id=RUN, payload=PAYLOAD)
        assert engine.execution_ref(RUN) == started.execution_ref
        assert ":execution:" in started.execution_ref
        assert started.execution_ref.endswith(f":{MACHINE}:{RUN}")
