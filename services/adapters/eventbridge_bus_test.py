"""The EventBridge adapter, against a real bus served by moto (WP-07).

The tests that matter here are the ones about a response that looks like a
success. ``PutEvents`` returns 200 and raises nothing when it refuses entries,
so an adapter can be wrong in the exact way that loses events without a single
error appearing anywhere. Those paths are driven by injecting the response
shape AWS documents, because moto has no reason to refuse a valid entry.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_events.client import EventBridgeClient

from services.adapters.eventbridge_bus import BATCH_LIMIT, EventBridgeBus
from services.application.ports import EventBus, PublishRejected
from services.domain.jobs import OutboxEvent

BUS = "proofpath-conformance"
REGION = "ap-south-1"
SOURCE = "proofpath.purchases"
MOMENT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)


def event(event_id: str, *, event_type: str = "purchase.checkout_requested") -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_id="pp-000001",
        aggregate_version=2,
        owner_id="owner-0001",
        occurred_at=MOMENT,
        reference="ref-1",
    )


@contextmanager
def bridge() -> Iterator[tuple[EventBridgeBus, EventBridgeClient]]:
    with mock_aws():
        client = boto3.client(
            "events",
            region_name=REGION,
            aws_access_key_id="conformance",
            aws_secret_access_key="conformance",
            aws_session_token="conformance",
        )
        client.create_event_bus(Name=BUS)
        yield EventBridgeBus(client=client, bus_name=BUS, source=SOURCE), client


def accepted(count: int) -> dict[str, Any]:
    return {"FailedEntryCount": 0, "Entries": [{"EventId": f"id-{i}"} for i in range(count)]}


def test_the_adapter_satisfies_the_port() -> None:
    with bridge() as (bus, _):
        assert isinstance(bus, EventBus)


def test_accepted_events_report_nothing() -> None:
    with bridge() as (bus, _):
        assert bus.publish([event("ev-000001"), event("ev-000002")]) == []


def test_an_entry_carries_the_event_as_its_detail() -> None:
    """A consumer parses the detail, so it has to be the event and not a summary."""
    with bridge() as (bus, client):
        with patch.object(client, "put_events", side_effect=client.put_events) as spy:
            bus.publish([event("ev-000001")])
        entry = spy.call_args.kwargs["Entries"][0]
    assert entry["Source"] == SOURCE
    assert entry["DetailType"] == "purchase.checkout_requested"
    assert entry["EventBusName"] == BUS
    detail = json.loads(entry["Detail"])
    assert detail["event_id"] == "ev-000001"
    assert detail["aggregate_version"] == 2
    assert isinstance(detail["aggregate_version"], int)


def test_the_detail_type_is_the_event_type_so_a_rule_can_select_on_it() -> None:
    with bridge() as (bus, client):
        with patch.object(client, "put_events", side_effect=client.put_events) as spy:
            bus.publish(
                [
                    event("ev-000001", event_type="purchase.prepare_requested"),
                    event("ev-000002", event_type="purchase.checkout_requested"),
                ]
            )
        types = [entry["DetailType"] for entry in spy.call_args.kwargs["Entries"]]
    assert types == ["purchase.prepare_requested", "purchase.checkout_requested"]


def test_a_refused_entry_is_reported_although_the_call_succeeded() -> None:
    """The trap. ``PutEvents`` returns 200 and raises nothing.

    An adapter that only looked for an exception would report a success for an
    event that was never published, the outbox row would be marked published,
    and nothing would ever retry it.
    """
    response = {
        "FailedEntryCount": 1,
        "Entries": [
            {"EventId": "id-0"},
            {"ErrorCode": "ThrottlingException", "ErrorMessage": "slow down"},
            {"EventId": "id-2"},
        ],
    }
    with bridge() as (bus, client):
        with patch.object(client, "put_events", return_value=response):
            rejected = bus.publish([event("ev-000001"), event("ev-000002"), event("ev-000003")])
    assert rejected == [PublishRejected(event_id="ev-000002", error_code="ThrottlingException")]


def test_a_rejection_is_matched_to_its_event_by_position() -> None:
    """The index is the only link back to the event, so it has to be honoured.

    An adapter that reported the first event for any failure would retry the
    wrong row and quietly drop the right one.
    """
    response = {
        "FailedEntryCount": 2,
        "Entries": [
            {"EventId": "id-0"},
            {"ErrorCode": "InternalException", "ErrorMessage": "boom"},
            {"ErrorCode": "ThrottlingException", "ErrorMessage": "slow down"},
        ],
    }
    with bridge() as (bus, client):
        with patch.object(client, "put_events", return_value=response):
            rejected = bus.publish([event("ev-000001"), event("ev-000002"), event("ev-000003")])
    assert [(r.event_id, r.error_code) for r in rejected] == [
        ("ev-000002", "InternalException"),
        ("ev-000003", "ThrottlingException"),
    ]


def test_more_events_than_one_call_allows_are_split_into_several() -> None:
    """``PutEvents`` caps a call at ten. The cap is the adapter's to handle."""
    events = [event(f"ev-{index:06d}") for index in range(BATCH_LIMIT + 3)]
    with bridge() as (bus, client):
        with patch.object(client, "put_events", side_effect=client.put_events) as spy:
            assert bus.publish(events) == []
        sizes = [len(call.kwargs["Entries"]) for call in spy.call_args_list]
    assert sizes == [BATCH_LIMIT, 3]


def test_a_rejection_in_a_later_batch_is_still_attributed_correctly() -> None:
    """Index alignment is per call, so the second batch must not be read with
    the first batch's offsets.
    """
    events = [event(f"ev-{index:06d}") for index in range(BATCH_LIMIT + 2)]
    second = {
        "FailedEntryCount": 1,
        "Entries": [{"EventId": "id-0"}, {"ErrorCode": "InternalException"}],
    }
    with bridge() as (bus, client):
        with patch.object(client, "put_events", side_effect=[accepted(BATCH_LIMIT), second]):
            rejected = bus.publish(events)
    assert [r.event_id for r in rejected] == [f"ev-{BATCH_LIMIT + 1:06d}"]


def test_publishing_nothing_calls_the_bus_not_at_all() -> None:
    with bridge() as (bus, client):
        with patch.object(client, "put_events", side_effect=client.put_events) as spy:
            assert bus.publish([]) == []
        assert spy.call_count == 0


def test_a_short_response_is_a_loud_failure_not_a_wrong_attribution() -> None:
    """If the bus answered for fewer entries than were sent, which event each
    result belongs to is unknowable. Raising beats guessing: a wrong attribution
    retries a published event and drops an unpublished one.
    """
    response = {"FailedEntryCount": 1, "Entries": [{"ErrorCode": "InternalException"}]}
    with bridge() as (bus, client):
        with patch.object(client, "put_events", return_value=response):
            with pytest.raises(ValueError):
                bus.publish([event("ev-000001"), event("ev-000002")])


def test_a_genuine_fault_is_raised_rather_than_reported_per_entry() -> None:
    with bridge() as (bus, client):
        with patch.object(client, "put_events", side_effect=ConnectionError("no route")):
            with pytest.raises(ConnectionError):
                bus.publish([event("ev-000001")])
