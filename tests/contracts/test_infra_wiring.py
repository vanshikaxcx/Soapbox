"""The deployment half of contracts the code already keeps (WP-07).

Two modules reason carefully about which messages to report for retry, and both
of those arguments evaporate unless the event source mapping declares
``FunctionResponseTypes: [ReportBatchItemFailures]``. Without it Lambda ignores
the reply entirely and treats every message in the batch as processed -- so a
refused EventBridge entry, a vanished outbox row and an unparseable message are
all silently deleted, and nothing in the Python would look wrong.

That is not a property any unit test can hold, because it lives in YAML. So it
is asserted here, against the template itself.

**The functions are not declared yet.** Their packaging is WP-01's -- the
workers import across the whole ``services`` tree, so ``CodeUri`` cannot be the
workers directory, and SAM builds a Python function from a requirements.txt
inside its own ``CodeUri``. Rather than guess and break the build job, the rule
is written so that it applies the moment a function *is* added: any DynamoDB or
SQS event source in this template must declare the response type. Today it holds
over an empty set, and the test that says so is explicit about it rather than
quietly passing.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

TEMPLATE = pathlib.Path(__file__).resolve().parents[2] / "infra" / "template.yaml"

#: Event source types whose whole retry story depends on the reply being read.
BATCHED_SOURCES = ("DynamoDB", "SQS", "Kinesis", "MSK", "MQ", "DocumentDB")

REPORT_BATCH_ITEM_FAILURES = "ReportBatchItemFailures"


class CloudFormationLoader(yaml.SafeLoader):
    """A loader that tolerates CloudFormation's short tags.

    ``!Ref`` and ``!GetAtt`` are not YAML that ``SafeLoader`` knows. They are
    read as plain values here because this test is about structure, not about
    resolving anything.
    """


def _short_tag(loader: yaml.Loader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    raise TypeError(f"unexpected node under a CloudFormation tag: {node!r}")


CloudFormationLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: _short_tag(loader, node)
)


@pytest.fixture(scope="module")
def template() -> dict[str, Any]:
    parsed = yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=CloudFormationLoader)
    assert isinstance(parsed, dict)
    return parsed


def resources(template: dict[str, Any]) -> dict[str, Any]:
    found = template.get("Resources")
    assert isinstance(found, dict) and found, "the template declares no resources"
    return found


def batched_event_sources(template: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every (function, event name, event) whose source is delivered in batches."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for name, resource in resources(template).items():
        if resource.get("Type") != "AWS::Serverless::Function":
            continue
        events = resource.get("Properties", {}).get("Events", {}) or {}
        for event_name, event in events.items():
            if event.get("Type") in BATCHED_SOURCES:
                found.append((name, event_name, event))
    return found


# -- the rule that cannot be expressed in Python ---------------------------


def test_every_batched_event_source_reports_item_failures(template: dict[str, Any]) -> None:
    """Without this, both partial-batch handlers are a no-op.

    Lambda ignores ``batchItemFailures`` unless the mapping opts in, and treats
    the whole batch as processed. Every message a handler asked to have
    redelivered is deleted instead -- silently, with nothing in the Python to
    look at.
    """
    for function, event_name, event in batched_event_sources(template):
        declared = event.get("Properties", {}).get("FunctionResponseTypes") or []
        assert REPORT_BATCH_ITEM_FAILURES in declared, (
            f"{function}.{event_name} is a batched source without "
            f"{REPORT_BATCH_ITEM_FAILURES}; Lambda would discard the reply and "
            "delete every message the handler asked to retry"
        )


def test_the_functions_are_not_wired_yet_and_that_is_recorded(
    template: dict[str, Any],
) -> None:
    """The rule above currently holds over nothing, and says so out loud.

    A vacuous assertion that nobody knows is vacuous is worse than no assertion.
    When WP-01 adds the publisher and consumer this test fails, and whoever is
    holding it then has to delete it *and* satisfy the rule above -- which is the
    order those two things should happen in.
    """
    assert batched_event_sources(template) == [], (
        "a batched event source now exists: delete this test, and make sure "
        f"{REPORT_BATCH_ITEM_FAILURES} and the INSERT/OUTBOX# stream filter are "
        "declared on it"
    )


# -- the seam P4 asked for -------------------------------------------------


def test_the_names_p4_owns_are_parameters_not_literals(template: dict[str, Any]) -> None:
    """O-2 is unanswered, so the template takes the names rather than inventing
    them. A default here would be a decision nobody made.
    """
    parameters = template.get("Parameters", {})
    for required in ("TableName", "EventBusName", "JobQueueName", "JobDeadLetterQueueName"):
        assert required in parameters, f"{required} should be a parameter"
        assert "Default" not in parameters[required], (
            f"{required} has a default; a made-up name is a placeholder, and a "
            "placeholder is what P4 asked not to be given"
        )


# -- the queue that makes the redelivery argument true ---------------------


def test_the_queue_dead_letters_rather_than_redelivering_for_ever(
    template: dict[str, Any],
) -> None:
    """Both handlers report an unusable message so it is redelivered and then
    dead-lettered, because a partial-batch reply cannot say "dead-letter this
    now" and reporting success would delete a committed command. With no
    redrive policy that message is simply redelivered for ever.
    """
    queue = resources(template)["JobQueue"]
    redrive = queue["Properties"]["RedrivePolicy"]
    assert "deadLetterTargetArn" in redrive
    assert redrive["maxReceiveCount"] == "MaxReceiveCount"


def test_the_dead_letter_queue_keeps_messages_long_enough_to_be_found(
    template: dict[str, Any],
) -> None:
    """A dead-lettered message is the last trace of a committed command."""
    queue = resources(template)["JobDeadLetterQueue"]
    assert queue["Properties"]["MessageRetentionPeriod"] == 1209600


# -- the table the adapter is written against ------------------------------


def test_the_table_declares_the_keys_the_adapter_writes(template: dict[str, Any]) -> None:
    """The other half of the PK/SK contract.

    DynamoDB attribute names are case-sensitive, so a mismatch between this and
    ``dynamo_state_store`` reads as an empty table rather than as an error, and
    a conditional write that should have been refused is allowed instead.
    """
    from services.adapters.dynamo_state_store import PARTITION_ATTRIBUTE, SORT_ATTRIBUTE

    table = resources(template)["ProofPathTable"]["Properties"]
    attributes = {entry["AttributeName"] for entry in table["AttributeDefinitions"]}
    assert attributes == {PARTITION_ATTRIBUTE, SORT_ATTRIBUTE}
    schema = {entry["KeyType"]: entry["AttributeName"] for entry in table["KeySchema"]}
    assert schema == {"HASH": PARTITION_ATTRIBUTE, "RANGE": SORT_ATTRIBUTE}


def test_the_table_has_a_stream_for_the_publisher_to_read(template: dict[str, Any]) -> None:
    table = resources(template)["ProofPathTable"]["Properties"]
    assert table["StreamSpecification"]["StreamViewType"] == "NEW_AND_OLD_IMAGES"
