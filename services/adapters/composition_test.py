"""The composition root: what an environment selects, and what it refuses.

The tests that matter most are the refusals. A composition root that guesses is
worse than one that fails, because the guess is invisible: an in-memory store
chosen by accident accepts every write, loses every one of them, and reports
success while doing it.

The environment is passed in rather than read from ``os.environ`` here, so no
test can leave a variable set for the next one.
"""

from __future__ import annotations

import pytest

from services.adapters.composition import (
    AWS,
    BUS_BACKEND,
    BUS_NAME,
    EVENT_SOURCE,
    MEMORY,
    REGION,
    STATE_MACHINE_ARN,
    STORE_BACKEND,
    TABLE_NAME,
    WORKFLOW_BACKEND,
    MisconfiguredEnvironment,
    build_event_bus,
    build_state_store,
    build_workflow_engine,
)
from services.adapters.dynamo_state_store import DynamoStateStore
from services.adapters.eventbridge_bus import EventBridgeBus
from services.adapters.stepfunctions_engine import StepFunctionsEngine
from services.application.fakes import (
    MemoryStore,
    RecordingEventBus,
    RecordingWorkflowEngine,
)
from services.application.ports import EventBus, StateStore, WorkflowEngine

AWS_STORE = {STORE_BACKEND: AWS, TABLE_NAME: "proofpath-main", REGION: "ap-south-1"}
AWS_BUS = {
    BUS_BACKEND: AWS,
    BUS_NAME: "proofpath-main",
    EVENT_SOURCE: "proofpath.purchases",
    REGION: "ap-south-1",
}
AWS_ENGINE = {
    WORKFLOW_BACKEND: AWS,
    STATE_MACHINE_ARN: "arn:aws:states:ap-south-1:1:stateMachine:jobs",
    REGION: "ap-south-1",
}


def test_memory_is_selectable_by_configuration_alone() -> None:
    """A rollback is a configuration change, not a revert."""
    assert isinstance(build_state_store({STORE_BACKEND: MEMORY}), MemoryStore)
    assert isinstance(build_event_bus({BUS_BACKEND: MEMORY}), RecordingEventBus)
    assert isinstance(build_workflow_engine({WORKFLOW_BACKEND: MEMORY}), RecordingWorkflowEngine)


def test_aws_is_selectable_by_configuration_alone() -> None:
    assert isinstance(build_state_store(AWS_STORE), DynamoStateStore)
    assert isinstance(build_event_bus(AWS_BUS), EventBridgeBus)
    assert isinstance(build_workflow_engine(AWS_ENGINE), StepFunctionsEngine)


def test_whatever_is_selected_satisfies_the_port() -> None:
    """Both sides of the switch are interchangeable, which is the only reason
    selecting between them at the edge is safe.
    """
    for environment in ({STORE_BACKEND: MEMORY}, AWS_STORE):
        assert isinstance(build_state_store(environment), StateStore)
    for environment in ({BUS_BACKEND: MEMORY}, AWS_BUS):
        assert isinstance(build_event_bus(environment), EventBus)
    for environment in ({WORKFLOW_BACKEND: MEMORY}, AWS_ENGINE):
        assert isinstance(build_workflow_engine(environment), WorkflowEngine)


def test_an_unset_backend_is_refused_rather_than_defaulted() -> None:
    """Defaulting to memory would lose every write and report success."""
    with pytest.raises(MisconfiguredEnvironment, match=STORE_BACKEND):
        build_state_store({})
    with pytest.raises(MisconfiguredEnvironment, match=BUS_BACKEND):
        build_event_bus({})
    with pytest.raises(MisconfiguredEnvironment, match=WORKFLOW_BACKEND):
        build_workflow_engine({})


def test_an_unrecognised_backend_names_what_was_expected() -> None:
    with pytest.raises(MisconfiguredEnvironment, match="dynamo"):
        build_state_store({STORE_BACKEND: "dynamo"})


def test_the_aws_store_refuses_to_start_without_a_table_name() -> None:
    """Failing at startup beats writing to a table nobody chose."""
    with pytest.raises(MisconfiguredEnvironment, match=TABLE_NAME):
        build_state_store({STORE_BACKEND: AWS, REGION: "ap-south-1"})


def test_the_aws_bus_refuses_to_start_without_a_bus_or_a_source() -> None:
    with pytest.raises(MisconfiguredEnvironment, match=BUS_NAME):
        build_event_bus({BUS_BACKEND: AWS, EVENT_SOURCE: "s", REGION: "ap-south-1"})
    with pytest.raises(MisconfiguredEnvironment, match=EVENT_SOURCE):
        build_event_bus({BUS_BACKEND: AWS, BUS_NAME: "b", REGION: "ap-south-1"})


def test_an_empty_string_counts_as_unset() -> None:
    """An unset variable and one set to nothing are the same configuration bug,
    and a deploy template is entirely capable of producing the second.
    """
    with pytest.raises(MisconfiguredEnvironment, match=TABLE_NAME):
        build_state_store({STORE_BACKEND: AWS, TABLE_NAME: "", REGION: "ap-south-1"})


def test_the_engine_refuses_to_start_without_a_state_machine() -> None:
    """Starting executions of a state machine nobody named is not a thing to
    guess at: the wrong one would run the wrong workflow under the right name.
    """
    with pytest.raises(MisconfiguredEnvironment, match=STATE_MACHINE_ARN):
        build_workflow_engine({WORKFLOW_BACKEND: AWS, REGION: "ap-south-1"})


def test_a_missing_region_is_named_like_any_other_variable() -> None:
    """Lambda always sets it, so an absent one means this is not running where
    it was meant to -- which is worth saying rather than letting botocore say
    something about endpoint resolution.
    """
    with pytest.raises(MisconfiguredEnvironment, match=REGION):
        build_state_store({STORE_BACKEND: AWS, TABLE_NAME: "proofpath-main"})


def test_the_store_and_the_bus_are_selected_independently() -> None:
    """A local run against a real table, or a real bus, has to be possible --
    otherwise the first integration test needs both halves at once.
    """
    assert isinstance(build_state_store({STORE_BACKEND: MEMORY}), MemoryStore)
    assert isinstance(build_event_bus(AWS_BUS), EventBridgeBus)
