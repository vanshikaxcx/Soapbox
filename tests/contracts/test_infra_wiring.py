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


def test_the_job_consumer_is_still_absent_and_the_reason_is_recorded(
    template: dict[str, Any],
) -> None:
    """The publisher is wired; the consumer is not, and that is deliberate.

    ``job_consumer.lambda_handler`` calls ``build_workflow_engine()``, which
    requires ``PROOFPATH_STATE_MACHINE_ARN`` -- and a state machine needs a task
    to run. No such handler exists in any package, and WP-07's spec names the
    controller and the execution naming but never the task itself.

    Filling that hole with a Pass state would report success for work nobody
    did, which is the failure this whole package exists to prevent. So the
    consumer waits for its task to be specified, and this test is what stops
    that waiting from being forgotten: when the task lands and the consumer is
    declared, this fails, and whoever is holding it deletes it *and* satisfies
    the batched-source rule above -- in that order.
    """
    declared = resources(template)
    assert "JobConsumerFunction" not in declared, (
        "the job consumer now exists: delete this test, and make sure its SQS "
        f"event source declares {REPORT_BATCH_ITEM_FAILURES} and that a state "
        "machine with a real task backs PROOFPATH_STATE_MACHINE_ARN"
    )
    assert "ProofPathStateMachine" not in declared, (
        "a state machine now exists: confirm its task does real work rather "
        "than passing, then delete this test"
    )


# -- the seam P4 asked for -------------------------------------------------


def test_the_published_event_actually_reaches_the_queue(template: dict[str, Any]) -> None:
    """O-2 is answered, so this is no longer about names.

    It was once: the template took the queue and table names as parameters
    because P4 had not settled them, and a default would have been a decision
    nobody made. WP-01 settled them -- the canonical ``AppTable`` and
    ``maxReceiveCount: 5`` are its answers -- so the question is now whether the
    routing those names produced is actually joined up.

    The publisher puts an event on the bus and the consumer reads the queue.
    Nothing in either module can tell that a rule connects the two, so a
    mismatch here is invisible in Python and shows up as jobs that are committed
    and then never run.
    """
    declared = resources(template)
    rule = declared["JobRule"]["Properties"]
    assert rule["EventBusName"] == "ProofPathEventBus", "the rule listens on the wrong bus"
    targets = [target["Arn"] for target in rule["Targets"]]
    assert "JobQueue.Arn" in targets, f"the rule does not target the job queue: {targets}"

    # The queue only accepts EventBridge from this rule; a wider policy would
    # let any rule in the account enqueue work.
    statement = declared["JobQueuePolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    assert statement["Condition"]["ArnEquals"]["aws:SourceArn"] == "JobRule.Arn"


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
    assert redrive["maxReceiveCount"] == 5, "WP-01 settled this at 5 (O-2)"


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

    table = resources(template)["AppTable"]["Properties"]
    attributes = {entry["AttributeName"] for entry in table["AttributeDefinitions"]}
    assert attributes == {PARTITION_ATTRIBUTE, SORT_ATTRIBUTE}
    schema = {entry["KeyType"]: entry["AttributeName"] for entry in table["KeySchema"]}
    assert schema == {"HASH": PARTITION_ATTRIBUTE, "RANGE": SORT_ATTRIBUTE}


def test_the_table_has_a_stream_for_the_publisher_to_read(template: dict[str, Any]) -> None:
    table = resources(template)["AppTable"]["Properties"]
    assert table["StreamSpecification"]["StreamViewType"] == "NEW_AND_OLD_IMAGES"
