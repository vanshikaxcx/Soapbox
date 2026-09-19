"""The consumer, and the loop it closes (WP-07).

Three groups. The first is the reply SQS acts on -- which message ids come back
and which do not. The second is duplicate delivery, which is the whole reason
this handler is allowed to be this simple: it has no dedupe of its own, so the
tests have to show that the execution name is enough.

The third walks the entire path in one test, driven by WP-08's real approval use
case rather than by rows this file invented: approve a purchase, publish the
outbox row it committed, hand the published event to the consumer as SQS would
deliver it, and find a Step Functions execution running. Once against the fakes,
once against DynamoDB, EventBridge and Step Functions under moto.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import boto3
from moto import mock_aws

from services.adapters.dynamo_state_store import (
    PARTITION_ATTRIBUTE,
    SORT_ATTRIBUTE,
    DynamoStateStore,
)
from services.adapters.eventbridge_bus import BATCH_LIMIT, EventBridgeBus
from services.adapters.stepfunctions_engine import StepFunctionsEngine
from services.application.controller import JobController
from services.application.fakes import (
    MemoryStore,
    RecordingEventBus,
    RecordingWorkflowEngine,
)
from services.application.outbox import OutboxPublisher, job_id_of
from services.application.ports import StateStore, Write, read
from services.application.purchase import job_key, outbox_key
from services.application.purchase_test import World
from services.domain.jobs import Job, OutboxEvent, PublicationState
from services.domain.transitions import JobState
from services.workers.job_consumer import (
    Message,
    batch_response,
    create_job_consumer,
    parse_queue_batch,
)

MOMENT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
JOB_ID = "job-0000001"
REGION = "ap-south-1"
TABLE = "proofpath-loop"
BUS = "proofpath-loop"
MACHINE = "proofpath-loop"
SOURCE = "proofpath.purchases"
DEFINITION = json.dumps({"StartAt": "Done", "States": {"Done": {"Type": "Pass", "End": True}}})


def event(event_id: str = "ev-000001", *, job_id: str = JOB_ID) -> OutboxEvent:
    """An outbox event shaped the way WP-08 commits one: reference is the job."""
    return OutboxEvent(
        event_id=event_id,
        event_type="purchase.checkout_requested",
        aggregate_id="pp-000001",
        aggregate_version=2,
        owner_id="owner-0001",
        occurred_at=MOMENT,
        reference=job_id,
    )


def job(*, job_id: str = JOB_ID, status: JobState = JobState.QUEUED) -> Job:
    from services.domain.jobs import JobType

    return Job(
        job_id=job_id,
        owner_id="owner-0001",
        job_type=JobType.CHECKOUT,
        input_hash="a" * 64,
        reference="attempt-0001",
        status=status,
        created_at=MOMENT,
    )


def envelope(outbox_event: OutboxEvent) -> str:
    """What EventBridge puts on the queue: our detail inside its envelope."""
    return json.dumps(
        {
            "version": "0",
            "id": "1e0a3f0c",
            "detail-type": outbox_event.event_type,
            "source": SOURCE,
            "region": REGION,
            "resources": [outbox_event.aggregate_id],
            "detail": json.loads(outbox_event.model_dump_json()),
        }
    )


def message(*, message_id: str, body: str) -> dict[str, Any]:
    return {"messageId": message_id, "receiptHandle": f"rh-{message_id}", "body": body}


def queue(*records: dict[str, Any]) -> dict[str, Any]:
    return {"Records": list(records)}


class FaultyEngine:
    """A workflow engine that refuses to start particular runs.

    The fault is injected at the engine rather than by patching the controller,
    for two reasons. ``JobController`` is a frozen slots dataclass, so it cannot
    be patched at all -- and more to the point, an engine is where a throttle or
    a dropped connection actually comes from, so this is the real shape of the
    failure rather than a stand-in for it.
    """

    def __init__(self, inner: RecordingWorkflowEngine, *, breaks: set[str] | None = None) -> None:
        self._inner = inner
        #: Run ids to fail on. ``None`` means every one of them: a total outage.
        self._breaks = breaks

    def start(self, *, run_id: str, payload: str) -> Any:
        if self._breaks is None or run_id in self._breaks:
            raise ConnectionError("no route to the engine")
        return self._inner.start(run_id=run_id, payload=payload)

    def status(self, *, execution_ref: str) -> Any:
        return self._inner.status(execution_ref=execution_ref)


def seeded(*rows: Job) -> MemoryStore:
    store = MemoryStore()
    store.transact([Write(key=job_key(j.job_id), item=j, reason="committed") for j in rows])
    return store


# -- reading the batch ------------------------------------------------------


def test_a_queued_event_becomes_a_message_naming_its_job() -> None:
    batch = parse_queue_batch(queue(message(message_id="m-1", body=envelope(event()))))
    assert batch.messages == (Message(message_id="m-1", job_id=JOB_ID),)
    assert batch.unreadable == ()


def test_the_identifier_is_the_sqs_message_id_not_a_sequence_number() -> None:
    """Streams retries by position, SQS by message. Neither validates the
    other's identifier, so conflating them retries the wrong thing silently.
    """
    batch = parse_queue_batch(queue(message(message_id="9d4f-aa21", body=envelope(event()))))
    assert batch.messages[0].message_id == "9d4f-aa21"


def test_the_job_comes_from_the_events_reference() -> None:
    """``OutboxEvent.reference`` is the job id; ``Job.reference`` is not.

    The same field name means different things on the two envelopes, and routing
    on the wrong one would look up a job that does not exist.
    """
    batch = parse_queue_batch(
        queue(message(message_id="m-1", body=envelope(event(job_id="job-0000777"))))
    )
    assert batch.messages[0].job_id == "job-0000777"


def test_a_body_that_is_not_json_is_reported_rather_than_dropped() -> None:
    batch = parse_queue_batch(queue(message(message_id="m-1", body="not json at all")))
    assert batch.messages == ()
    assert batch.unreadable == ("m-1",)


def test_an_envelope_with_no_detail_is_reported() -> None:
    batch = parse_queue_batch(queue(message(message_id="m-1", body=json.dumps({"source": SOURCE}))))
    assert batch.unreadable == ("m-1",)


def test_a_detail_that_is_not_the_committed_record_is_reported() -> None:
    """Validated as the domain's own envelope, because a detail that has been
    through two services and no longer reproduces the record WP-08 committed is
    not something to act on half-understood.
    """
    body = json.dumps({"detail": {"event_id": "ev-000001", "event_type": "x"}})
    assert parse_queue_batch(queue(message(message_id="m-1", body=body))).unreadable == ("m-1",)


def test_a_message_with_no_id_cannot_be_reported_so_is_left_alone() -> None:
    batch = parse_queue_batch({"Records": [{"body": envelope(event())}]})
    assert batch.messages == ()
    assert batch.unreadable == ()


def test_nothing_failed_means_an_empty_list_not_an_absent_one() -> None:
    assert batch_response([]) == {"batchItemFailures": []}


# -- the handler ------------------------------------------------------------


def test_a_clean_batch_starts_every_job_and_reports_nothing() -> None:
    store = seeded(job(job_id="job-0000001"), job(job_id="job-0000002"))
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    reply = handler(
        queue(
            message(message_id="m-1", body=envelope(event("ev-000001", job_id="job-0000001"))),
            message(message_id="m-2", body=envelope(event("ev-000002", job_id="job-0000002"))),
        ),
        None,
    )
    assert reply == {"batchItemFailures": []}
    assert sorted(engine.started) == ["job-0000001-r1", "job-0000002-r1"]


def test_one_failed_message_does_not_fail_the_batch() -> None:
    """The reason the reply has this shape at all.

    The middle message names a job that is not there. The two beside it must
    start, and only the one that failed comes back.
    """
    store = seeded(job(job_id="job-0000001"), job(job_id="job-0000003"))
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    reply = handler(
        queue(
            message(message_id="m-1", body=envelope(event("ev-000001", job_id="job-0000001"))),
            message(message_id="m-2", body=envelope(event("ev-000002", job_id="job-0000404"))),
            message(message_id="m-3", body=envelope(event("ev-000003", job_id="job-0000003"))),
        ),
        None,
    )
    assert reply == {"batchItemFailures": [{"itemIdentifier": "m-2"}]}
    assert sorted(engine.started) == ["job-0000001-r1", "job-0000003-r1"]


def test_an_unreadable_message_does_not_fail_the_batch_either() -> None:
    store = seeded(job())
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    reply = handler(
        queue(
            message(message_id="m-1", body="}{"),
            message(message_id="m-2", body=envelope(event())),
        ),
        None,
    )
    assert reply == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}
    assert engine.started == ["job-0000001-r1"]


def test_a_missing_job_is_reported_so_it_reaches_the_dead_letter_queue() -> None:
    """The job row and the outbox row are committed in one transaction, so a
    missing job cannot be a race and a retry will not invent it. Reporting it
    keeps the evidence; treating it as success would delete the only trace.
    """
    handler = create_job_consumer(
        JobController(store=MemoryStore(), engine=RecordingWorkflowEngine())
    )
    reply = handler(queue(message(message_id="m-1", body=envelope(event()))), None)
    assert reply == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}


def test_a_fault_on_one_message_leaves_the_others_alone() -> None:
    """Opposite of the publisher, and deliberately so: ``deliver`` is called per
    message, so a fault has a single owning message and reporting only that one
    is the entire point of a partial-batch reply.
    """
    store = seeded(job(job_id="job-0000001"), job(job_id="job-0000002"))
    inner = RecordingWorkflowEngine()
    engine = FaultyEngine(inner, breaks={"job-0000001-r1"})
    handler = create_job_consumer(JobController(store=store, engine=engine))
    reply = handler(
        queue(
            message(message_id="m-1", body=envelope(event("ev-000001", job_id="job-0000001"))),
            message(message_id="m-2", body=envelope(event("ev-000002", job_id="job-0000002"))),
        ),
        None,
    )
    assert reply == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}
    assert inner.started == ["job-0000002-r1"]
    assert inner.runs() == 1


def test_a_total_outage_reports_every_message_and_loses_none() -> None:
    store = seeded(job(job_id="job-0000001"), job(job_id="job-0000002"))
    inner = RecordingWorkflowEngine()
    handler = create_job_consumer(
        JobController(store=store, engine=FaultyEngine(inner, breaks=None))
    )
    reply = handler(
        queue(
            message(message_id="m-1", body=envelope(event("ev-000001", job_id="job-0000001"))),
            message(message_id="m-2", body=envelope(event("ev-000002", job_id="job-0000002"))),
        ),
        None,
    )
    assert reply == {"batchItemFailures": [{"itemIdentifier": "m-1"}, {"itemIdentifier": "m-2"}]}
    assert inner.runs() == 0, "an outage must leave nothing half-started"


# -- duplicate delivery -----------------------------------------------------


def test_the_same_event_twice_resolves_twice_and_runs_once() -> None:
    store = seeded(job())
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    body = envelope(event())
    assert handler(queue(message(message_id="m-1", body=body)), None) == {"batchItemFailures": []}
    assert handler(queue(message(message_id="m-2", body=body)), None) == {"batchItemFailures": []}
    assert engine.runs() == 1


def test_the_republished_batch_of_ten_yields_ten_resolutions_and_one_run() -> None:
    """The concrete duplicate this design produces, end to end.

    ``PutEvents`` accepts the first ten entries, the connection drops on the
    eleventh, the whole batch is retried and those ten go out again. Every
    consumer sees each of them twice. Ten duplicate events, ten successful
    resolutions, one execution -- and no deduplication anywhere in the consumer.
    """
    store = seeded(job())
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    body = envelope(event())
    for delivery in range(BATCH_LIMIT):
        reply = handler(queue(message(message_id=f"m-{delivery}", body=body)), None)
        assert reply == {"batchItemFailures": []}, f"delivery {delivery} was not resolved"
    assert engine.runs() == 1
    assert read(store, job_key(JOB_ID), Job).generation == 1  # type: ignore[union-attr]


def test_ten_duplicates_in_one_batch_also_yield_one_run() -> None:
    """The same thing arriving together rather than one at a time."""
    store = seeded(job())
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    body = envelope(event())
    reply = handler(
        queue(*(message(message_id=f"m-{n}", body=body) for n in range(BATCH_LIMIT))), None
    )
    assert reply == {"batchItemFailures": []}
    assert engine.runs() == 1


def test_a_duplicate_never_increments_the_generation() -> None:
    """A replay that produced a generation would produce a new name, and the
    suppression the name provides would be bypassed entirely.
    """
    store = seeded(job())
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    body = envelope(event())
    for n in range(5):
        handler(queue(message(message_id=f"m-{n}", body=body)), None)
    row = read(store, job_key(JOB_ID), Job)
    assert row is not None
    assert row.generation == 1
    assert row.run_id == "job-0000001-r1"


# -- the whole loop ---------------------------------------------------------


def approved() -> MemoryStore:
    """A store holding exactly what WP-08's approval transaction commits.

    Driven through the real use case, not assembled here: the point of the loop
    test is that the rows it walks are the rows production writes, including the
    ``reference=job_id`` contract the consumer routes on.

    Typed as the fake because the loop test that runs on the real adapters hands
    these rows on with ``snapshot()``, which only the fake has. That is the
    honest shape: WP-08 commits into its own store, and the rows are copied.
    """
    world = World()
    world.approve_ok()
    return world.memory


def committed_event(store: StateStore) -> OutboxEvent:
    keys = store.keys_matching("OUTBOX#")
    assert len(keys) == 1, f"expected one committed outbox row, found {keys}"
    found = read(store, keys[0], OutboxEvent)
    assert found is not None
    return found


def test_wp08_commits_an_event_whose_reference_is_the_job_it_dispatches() -> None:
    """The contract the consumer depends on, pinned against WP-08's own output.

    If WP-08 ever "tidied" ``reference`` to mean the same thing on both
    envelopes, the consumer would route to a job that does not exist and every
    event would be dead-lettered. This test is what fails instead.
    """
    store = approved()
    outbox_event = committed_event(store)
    committed_job = read(store, job_key(job_id_of(outbox_event)), Job)
    assert committed_job is not None, "the event's reference must name a committed job"
    assert committed_job.job_id == outbox_event.reference
    assert committed_job.status is JobState.QUEUED


def test_the_whole_loop_runs_against_the_fakes() -> None:
    """Committed row, published event, queued delivery, running execution."""
    store = approved()
    bus = RecordingEventBus()
    engine = RecordingWorkflowEngine()
    outbox_event = committed_event(store)

    published = OutboxPublisher(store=store, bus=bus).publish([outbox_event.event_id])
    assert published.published == (outbox_event.event_id,)

    handler = create_job_consumer(JobController(store=store, engine=engine))
    delivered = bus.published[0]
    reply = handler(queue(message(message_id="m-1", body=envelope(delivered))), None)

    assert reply == {"batchItemFailures": []}
    assert engine.runs() == 1
    started = read(store, job_key(job_id_of(delivered)), Job)
    assert started is not None
    assert started.status is JobState.RUNNING
    assert started.execution_ref is not None
    assert started.run_id == f"{started.job_id}-r1"


@contextmanager
def deployed() -> Iterator[tuple[DynamoStateStore, EventBridgeBus, StepFunctionsEngine, Any, str]]:
    """All three production adapters, in-process. No account, no network."""
    with mock_aws():
        dynamodb = boto3.client(
            "dynamodb",
            region_name=REGION,
            aws_access_key_id="loop",
            aws_secret_access_key="loop",
            aws_session_token="loop",
        )
        dynamodb.create_table(
            TableName=TABLE,
            AttributeDefinitions=[
                {"AttributeName": PARTITION_ATTRIBUTE, "AttributeType": "S"},
                {"AttributeName": SORT_ATTRIBUTE, "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": PARTITION_ATTRIBUTE, "KeyType": "HASH"},
                {"AttributeName": SORT_ATTRIBUTE, "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        events = boto3.client(
            "events",
            region_name=REGION,
            aws_access_key_id="loop",
            aws_secret_access_key="loop",
            aws_session_token="loop",
        )
        events.create_event_bus(Name=BUS)
        iam = boto3.client(
            "iam",
            region_name=REGION,
            aws_access_key_id="loop",
            aws_secret_access_key="loop",
            aws_session_token="loop",
        )
        role = iam.create_role(RoleName="proofpath-loop", AssumeRolePolicyDocument="{}")["Role"][
            "Arn"
        ]
        sfn = boto3.client(
            "stepfunctions",
            region_name=REGION,
            aws_access_key_id="loop",
            aws_secret_access_key="loop",
            aws_session_token="loop",
        )
        arn = sfn.create_state_machine(name=MACHINE, definition=DEFINITION, roleArn=role)[
            "stateMachineArn"
        ]
        yield (
            DynamoStateStore(client=dynamodb, table_name=TABLE),
            EventBridgeBus(client=events, bus_name=BUS, source=SOURCE),
            StepFunctionsEngine(client=sfn, state_machine_arn=arn),
            sfn,
            arn,
        )


def test_the_whole_loop_runs_against_the_real_adapters() -> None:
    """The same walk, on DynamoDB, EventBridge and Step Functions under moto.

    WP-08 commits into its own fake, and every row it wrote is then handed to
    the real store in one transaction -- which also puts each of its record types
    through the adapter's codec. From there nothing is simulated: the event is
    published to a real bus, delivered as SQS would deliver it, and the run is
    counted by asking Step Functions.
    """
    with deployed() as (store, bus, engine, sfn, machine_arn):
        committed = approved().snapshot()
        assert (
            store.transact(
                [
                    Write(key=key, item=item, reason="as WP-08 committed it")
                    for key, item in committed.items()
                ]
            )
            is None
        )

        outbox_event = committed_event(store)
        assert OutboxPublisher(store=store, bus=bus).publish([outbox_event.event_id]).published == (
            outbox_event.event_id,
        )

        handler = create_job_consumer(JobController(store=store, engine=engine))
        reply = handler(queue(message(message_id="m-1", body=envelope(outbox_event))), None)

        assert reply == {"batchItemFailures": []}
        started = read(store, job_key(job_id_of(outbox_event)), Job)
        assert started is not None
        assert started.status is JobState.RUNNING

        executions = sfn.list_executions(stateMachineArn=machine_arn)["executions"]
        assert [e["name"] for e in executions] == [started.run_id]

        row = read(store, outbox_key(outbox_event.event_id), OutboxEvent)
        assert row is not None
        assert row.publication_state is PublicationState.PUBLISHED


def test_a_redelivery_through_the_real_adapters_still_leaves_one_execution() -> None:
    """At-least-once, all the way through, with no dedupe in the consumer."""
    with deployed() as (store, bus, engine, sfn, machine_arn):
        committed = approved().snapshot()
        store.transact(
            [
                Write(key=key, item=item, reason="as WP-08 committed it")
                for key, item in committed.items()
            ]
        )
        outbox_event = committed_event(store)
        OutboxPublisher(store=store, bus=bus).publish([outbox_event.event_id])

        handler = create_job_consumer(JobController(store=store, engine=engine))
        body = envelope(outbox_event)
        for n in range(BATCH_LIMIT):
            assert handler(queue(message(message_id=f"m-{n}", body=body)), None) == {
                "batchItemFailures": []
            }

        executions = sfn.list_executions(stateMachineArn=machine_arn)["executions"]
        assert len(executions) == 1


def test_an_unusable_message_is_reported_like_any_other_failure() -> None:
    """The decision, stated: unreadable and job-missing get the same answer.

    They are genuinely different -- redelivery can never fix a body that will
    not parse, and is exactly the cure for a job that is not visible yet. But a
    partial-batch reply has only two words, "done" and "again", and "done"
    deletes the message. Choosing it for an unparseable body would destroy a
    committed command silently, which is worse than a bounded number of pointless
    redeliveries before the dead-letter queue takes it.
    """
    store = seeded(job())
    engine = RecordingWorkflowEngine()
    handler = create_job_consumer(JobController(store=store, engine=engine))
    reply = handler(
        queue(
            message(message_id="m-unparseable", body="}{"),
            message(message_id="m-missing", body=envelope(event(job_id="job-0000404"))),
            message(message_id="m-fine", body=envelope(event())),
        ),
        None,
    )
    reported = {failure["itemIdentifier"] for failure in reply["batchItemFailures"]}
    assert reported == {"m-unparseable", "m-missing"}
    assert engine.started == ["job-0000001-r1"]


def test_the_two_kinds_stay_apart_in_the_batch_even_though_they_answer_alike() -> None:
    """Kept structurally, so Stage 5's DLQ replay can tell them apart without
    re-deriving which was which.
    """
    batch = parse_queue_batch(
        queue(
            message(message_id="m-unparseable", body="}{"),
            message(message_id="m-fine", body=envelope(event())),
        )
    )
    assert batch.unreadable == ("m-unparseable",)
    assert [m.message_id for m in batch.messages] == ["m-fine"]
