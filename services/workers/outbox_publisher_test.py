"""The publisher's stream entry point, and one run through the real adapters.

Two halves. The first checks the reply shape Lambda acts on -- which records are
reported for retry and which are not -- because that reply is the only thing
standing between one malformed record and a batch that republishes every healthy
event beside it forever.

The second wires the DynamoDB store and the EventBridge bus that production will
use, both served in-process, and pushes a committed outbox row all the way onto
the bus. It exists so that when WP-01 lands there is nothing left but pointing
the same code at a real account.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from services.adapters.dynamo_state_store import (
    PARTITION_ATTRIBUTE,
    SORT_ATTRIBUTE,
    DynamoStateStore,
)
from services.adapters.eventbridge_bus import EventBridgeBus
from services.application.fakes import MemoryStore, RecordingEventBus
from services.application.outbox import OutboxPublisher
from services.application.ports import Write, read
from services.application.purchase import outbox_key
from services.domain.jobs import OutboxEvent, PublicationState
from services.workers.outbox_publisher import (
    Delivery,
    batch_response,
    create_outbox_handler,
    parse_stream_batch,
)

MOMENT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
TABLE = "proofpath-worker"
BUS = "proofpath-worker"
REGION = "ap-south-1"
SOURCE = "proofpath.purchases"


def event(event_id: str, *, state: PublicationState = PublicationState.PENDING) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        event_type="purchase.checkout_requested",
        aggregate_id="pp-000001",
        aggregate_version=2,
        owner_id="owner-0001",
        occurred_at=MOMENT,
        reference="ref-1",
        publication_state=state,
    )


def record(
    *, sequence: str, partition: str, name: str = "INSERT", keys: bool = True
) -> dict[str, Any]:
    stream: dict[str, Any] = {"SequenceNumber": sequence}
    if keys:
        stream["Keys"] = {
            PARTITION_ATTRIBUTE: {"S": partition},
            SORT_ATTRIBUTE: {"S": "EVENT"},
        }
    return {"eventID": f"e-{sequence}", "eventName": name, "dynamodb": stream}


def stream(*records: dict[str, Any]) -> dict[str, Any]:
    return {"Records": list(records)}


# -- reading the batch ------------------------------------------------------


def test_an_outbox_row_becomes_a_delivery() -> None:
    batch = parse_stream_batch(stream(record(sequence="1", partition="OUTBOX#ev-000001")))
    assert batch.deliveries == (Delivery(identifier="1", event_id="ev-000001"),)
    assert batch.unreadable == ()


def test_a_row_from_another_partition_is_not_this_workers_business() -> None:
    """The event source filter should have excluded it. This is the second line."""
    batch = parse_stream_batch(stream(record(sequence="1", partition="PURCHASE#pp-1")))
    assert batch == parse_stream_batch(stream())


def test_a_removed_row_has_nothing_left_to_publish() -> None:
    batch = parse_stream_batch(
        stream(record(sequence="1", partition="OUTBOX#ev-000001", name="REMOVE"))
    )
    assert batch.deliveries == ()


def test_the_sequence_number_is_what_lambda_retries_by() -> None:
    batch = parse_stream_batch(stream(record(sequence="4242", partition="OUTBOX#ev-000001")))
    assert batch.deliveries[0].identifier == "4242"


def test_a_record_with_no_identifier_cannot_be_reported_so_is_left_alone() -> None:
    """Naming it in the reply is impossible, and inventing an identifier would
    ask Lambda to retry a different record.
    """
    assert parse_stream_batch({"Records": [{"eventName": "INSERT"}]}).deliveries == ()


def test_an_outbox_record_with_no_event_id_is_reported_rather_than_dropped() -> None:
    """A lost outbox event has no other trace, so it is failed into the DLQ."""
    batch = parse_stream_batch(stream(record(sequence="1", partition="OUTBOX#")))
    assert batch.deliveries == ()
    assert batch.unreadable == ("1",)


def test_an_outbox_record_with_no_keys_is_reported_rather_than_dropped() -> None:
    batch = parse_stream_batch(stream(record(sequence="1", partition="x", keys=False)))
    assert batch.deliveries == ()


# -- the reply --------------------------------------------------------------


def test_nothing_failed_means_an_empty_list_not_an_absent_one() -> None:
    """An absent ``batchItemFailures`` means "retry everything"."""
    assert batch_response([]) == {"batchItemFailures": []}


def test_the_reply_names_each_identifier_once() -> None:
    assert batch_response(["1", "2", "1"]) == {
        "batchItemFailures": [{"itemIdentifier": "1"}, {"itemIdentifier": "2"}]
    }


# -- the handler ------------------------------------------------------------


def seeded(*events: OutboxEvent) -> MemoryStore:
    store = MemoryStore()
    store.transact(
        [Write(key=outbox_key(e.event_id), item=e, reason="committed by WP-08") for e in events]
    )
    return store


def test_a_clean_batch_reports_no_failures() -> None:
    store = seeded(event("ev-000001"), event("ev-000002"))
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=RecordingEventBus()))
    reply = handler(
        stream(
            record(sequence="1", partition="OUTBOX#ev-000001"),
            record(sequence="2", partition="OUTBOX#ev-000002"),
        ),
        None,
    )
    assert reply == {"batchItemFailures": []}


def test_only_the_refused_event_is_reported_for_retry() -> None:
    store = seeded(event("ev-000001"), event("ev-000002"), event("ev-000003"))
    bus = RecordingEventBus(refuse={"ev-000002": "ThrottlingException"})
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=bus))
    reply = handler(
        stream(
            record(sequence="1", partition="OUTBOX#ev-000001"),
            record(sequence="2", partition="OUTBOX#ev-000002"),
            record(sequence="3", partition="OUTBOX#ev-000003"),
        ),
        None,
    )
    assert reply == {"batchItemFailures": [{"itemIdentifier": "2"}]}


def test_one_bad_record_does_not_fail_the_whole_batch() -> None:
    """The defect this package's reply shape exists to prevent.

    A batch that failed wholesale because one record in it was malformed would
    republish every healthy event beside it on every redelivery, for as long as
    the bad record survived.
    """
    store = seeded(event("ev-000001"), event("ev-000002"))
    bus = RecordingEventBus()
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=bus))
    reply = handler(
        stream(
            record(sequence="1", partition="OUTBOX#ev-000001"),
            record(sequence="2", partition="OUTBOX#"),
            record(sequence="3", partition="OUTBOX#ev-000002"),
        ),
        None,
    )
    assert reply == {"batchItemFailures": [{"itemIdentifier": "2"}]}
    assert sorted(e.event_id for e in bus.published) == ["ev-000001", "ev-000002"]


def test_two_records_naming_one_event_are_both_answered() -> None:
    """Lambda retries by identifier, so every identifier has to be accounted for."""
    store = seeded(event("ev-000001"))
    bus = RecordingEventBus(refuse={"ev-000001": "InternalException"})
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=bus))
    reply = handler(
        stream(
            record(sequence="1", partition="OUTBOX#ev-000001"),
            record(sequence="2", partition="OUTBOX#ev-000001"),
        ),
        None,
    )
    assert reply == {"batchItemFailures": [{"itemIdentifier": "1"}, {"itemIdentifier": "2"}]}


def test_an_already_published_event_is_not_reported_for_retry() -> None:
    store = seeded(event("ev-000001", state=PublicationState.PUBLISHED))
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=RecordingEventBus()))
    reply = handler(stream(record(sequence="1", partition="OUTBOX#ev-000001")), None)
    assert reply == {"batchItemFailures": []}


def test_a_bus_outage_fails_the_whole_batch() -> None:
    """The one case where a whole-batch retry is the correct answer: nothing was
    published, so there is nothing to report per entry.
    """

    class BrokenBus:
        def publish(self, events: object) -> list[object]:
            raise ConnectionError("no route to the bus")

    store = seeded(event("ev-000001"))
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=BrokenBus()))  # type: ignore[arg-type]
    with pytest.raises(ConnectionError):
        handler(stream(record(sequence="1", partition="OUTBOX#ev-000001")), None)


# -- through the real adapters ----------------------------------------------


@contextmanager
def deployed() -> Iterator[tuple[DynamoStateStore, EventBridgeBus, Any]]:
    """Both production adapters, in-process. No account, no network."""
    with mock_aws():
        # Spelled out per client rather than splatted from a dict: boto3's
        # stubs pick the client type from the literal service name, and a
        # ``**kwargs`` call throws that away along with every check it buys.
        dynamodb = boto3.client(
            "dynamodb",
            region_name=REGION,
            aws_access_key_id="worker",
            aws_secret_access_key="worker",
            aws_session_token="worker",
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
            aws_access_key_id="worker",
            aws_secret_access_key="worker",
            aws_session_token="worker",
        )
        events.create_event_bus(Name=BUS)
        yield (
            DynamoStateStore(client=dynamodb, table_name=TABLE),
            EventBridgeBus(client=events, bus_name=BUS, source=SOURCE),
            events,
        )


def test_a_committed_row_reaches_the_bus_through_the_real_adapters() -> None:
    with deployed() as (store, bus, events):
        store.transact(
            [Write(key=outbox_key("ev-000001"), item=event("ev-000001"), reason="committed")]
        )
        handler = create_outbox_handler(OutboxPublisher(store=store, bus=bus))
        with patch.object(events, "put_events", side_effect=events.put_events) as spy:
            reply = handler(stream(record(sequence="1", partition="OUTBOX#ev-000001")), None)

        assert reply == {"batchItemFailures": []}
        detail = json.loads(spy.call_args.kwargs["Entries"][0]["Detail"])
        assert detail["event_id"] == "ev-000001"
        row = read(store, outbox_key("ev-000001"), OutboxEvent)
        assert row is not None
        assert row.publication_state is PublicationState.PUBLISHED


def test_a_redelivery_through_the_real_adapters_publishes_once() -> None:
    """At-least-once delivery, exactly-once publication in the ordinary case.

    The second delivery finds the row already published and skips it, which is
    what stops a replayed stream shard from re-emitting an entire day.
    """
    with deployed() as (store, bus, events):
        store.transact(
            [Write(key=outbox_key("ev-000001"), item=event("ev-000001"), reason="committed")]
        )
        handler = create_outbox_handler(OutboxPublisher(store=store, bus=bus))
        delivery = stream(record(sequence="1", partition="OUTBOX#ev-000001"))
        with patch.object(events, "put_events", side_effect=events.put_events) as spy:
            assert handler(delivery, None) == {"batchItemFailures": []}
            assert handler(delivery, None) == {"batchItemFailures": []}
        assert spy.call_count == 1


def test_a_vanished_row_is_reported_rather_than_answered_with_silence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A committed outbox row that is not there is not housekeeping.

    It used to be folded in with "already published" and dropped from the reply
    entirely, so the message was deleted and the only trace of a committed
    command went with it. Reported now, and logged: reporting is what gets it to
    a dead-letter queue where somebody sees it.
    """
    store = MemoryStore()
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=RecordingEventBus()))
    with caplog.at_level(logging.ERROR):
        reply = handler(stream(record(sequence="1", partition="OUTBOX#ev-000009")), None)
    assert reply == {"batchItemFailures": [{"itemIdentifier": "1"}]}
    assert "vanished" in caplog.text


def test_an_already_published_row_is_still_not_reported() -> None:
    """The other half of the split: redelivery of a sent event stays silent."""
    store = seeded(event("ev-000001", state=PublicationState.PUBLISHED))
    handler = create_outbox_handler(OutboxPublisher(store=store, bus=RecordingEventBus()))
    reply = handler(stream(record(sequence="1", partition="OUTBOX#ev-000001")), None)
    assert reply == {"batchItemFailures": []}
