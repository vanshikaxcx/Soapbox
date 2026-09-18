"""Where an adapter is chosen (WP-07).

The spec's rule is that the adapter is selected here, by environment, and never
by branching inside application code. The reason is not tidiness: a use case
that asked which store it had would have two behaviours, and only one of them
would be the one 951 tests describe. Every use case takes a port; this module is
the only thing that decides what is behind it.

**Nothing is defaulted.** An unset ``PROOFPATH_STORE_BACKEND`` does not quietly
select the in-memory store -- that would accept every write, lose every one of
them, and report success while doing it, which is the worst failure this system
can have. An unset variable is a configuration bug and is raised as one, at
startup, naming the variable. A rollback is still a configuration change rather
than a revert, which is what the spec asks for; it just has to be written down.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

import boto3

from services.adapters.dynamo_state_store import DynamoStateStore
from services.adapters.eventbridge_bus import EventBridgeBus
from services.adapters.stepfunctions_engine import StepFunctionsEngine
from services.application.ports import EventBus, StateStore, WorkflowEngine

STORE_BACKEND: Final = "PROOFPATH_STORE_BACKEND"
BUS_BACKEND: Final = "PROOFPATH_BUS_BACKEND"
TABLE_NAME: Final = "PROOFPATH_TABLE_NAME"
BUS_NAME: Final = "PROOFPATH_EVENT_BUS_NAME"
EVENT_SOURCE: Final = "PROOFPATH_EVENT_SOURCE"
WORKFLOW_BACKEND: Final = "PROOFPATH_WORKFLOW_BACKEND"
STATE_MACHINE_ARN: Final = "PROOFPATH_STATE_MACHINE_ARN"

#: AWS's own variable, not one of ours. Lambda sets it for every function, and
#: reading it here rather than letting botocore find it means the region is a
#: stated input: a client built from ambient process state cannot be tested and
#: fails differently on a laptop than in a deployment.
REGION: Final = "AWS_REGION"

MEMORY: Final = "memory"
AWS: Final = "aws"
BACKENDS: Final = (MEMORY, AWS)


class MisconfiguredEnvironment(RuntimeError):
    """A variable the composition root needs is missing or unrecognised.

    Raised, and raised at startup, because there is no safe way to continue:
    every alternative is a silently wrong backend, and a silently wrong backend
    is indistinguishable from a working one until the data is already gone.
    """


def build_state_store(env: Mapping[str, str] | None = None) -> StateStore:
    """The canonical store this process should use."""
    environment = os.environ if env is None else env
    backend = _backend(environment, STORE_BACKEND)
    if backend == MEMORY:
        return _memory_store()
    # Every variable is read before any client is built. Built first, a missing
    # table name would surface as whatever botocore complained about instead --
    # and "you must specify a region" does not tell an operator that
    # PROOFPATH_TABLE_NAME is the thing they forgot.
    table_name = _required(environment, TABLE_NAME)
    region = _required(environment, REGION)
    return DynamoStateStore(
        client=boto3.client("dynamodb", region_name=region), table_name=table_name
    )


def build_event_bus(env: Mapping[str, str] | None = None) -> EventBus:
    """The bus committed outbox rows are published to."""
    environment = os.environ if env is None else env
    backend = _backend(environment, BUS_BACKEND)
    if backend == MEMORY:
        return _memory_bus()
    bus_name = _required(environment, BUS_NAME)
    source = _required(environment, EVENT_SOURCE)
    region = _required(environment, REGION)
    return EventBridgeBus(
        client=boto3.client("events", region_name=region), bus_name=bus_name, source=source
    )


def build_workflow_engine(env: Mapping[str, str] | None = None) -> WorkflowEngine:
    """The engine a job's execution is started on and asked about."""
    environment = os.environ if env is None else env
    backend = _backend(environment, WORKFLOW_BACKEND)
    if backend == MEMORY:
        return _memory_engine()
    state_machine_arn = _required(environment, STATE_MACHINE_ARN)
    region = _required(environment, REGION)
    return StepFunctionsEngine(
        client=boto3.client("stepfunctions", region_name=region),
        state_machine_arn=state_machine_arn,
    )


def _backend(env: Mapping[str, str], variable: str) -> str:
    value = _required(env, variable)
    if value not in BACKENDS:
        raise MisconfiguredEnvironment(
            f"{variable} is {value!r}; expected one of {', '.join(BACKENDS)}"
        )
    return value


def _required(env: Mapping[str, str], variable: str) -> str:
    value = env.get(variable, "")
    if not value:
        raise MisconfiguredEnvironment(f"{variable} is not set")
    return value


def _memory_store() -> StateStore:
    """Imported inside the branch, not at module scope.

    ``fakes`` describes itself as test-only and it is: importing it eagerly
    would put it in every production image whether or not anything selects it.
    Deferring the import keeps "memory" a deliberate, local choice.
    """
    from services.application.fakes import MemoryStore

    return MemoryStore()


def _memory_bus() -> EventBus:
    from services.application.fakes import RecordingEventBus

    return RecordingEventBus()


def _memory_engine() -> WorkflowEngine:
    from services.application.fakes import RecordingWorkflowEngine

    return RecordingWorkflowEngine()


__all__ = [
    "AWS",
    "BACKENDS",
    "BUS_BACKEND",
    "BUS_NAME",
    "EVENT_SOURCE",
    "MEMORY",
    "REGION",
    "STATE_MACHINE_ARN",
    "STORE_BACKEND",
    "TABLE_NAME",
    "WORKFLOW_BACKEND",
    "MisconfiguredEnvironment",
    "build_event_bus",
    "build_state_store",
    "build_workflow_engine",
]
