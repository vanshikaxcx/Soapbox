"""The outbox publisher's entry point, driven by DynamoDB Streams (WP-07).

This module is transport and nothing else: it reads a stream batch, hands the
event ids to the use case, and renders the reply Lambda expects. No decision
about *what* to publish is made here, because the decision was made and
committed by the transaction that wrote the row.

**The partial-batch response is the whole point of the reply shape.** With
``ReportBatchItemFailures`` configured, returning an empty ``batchItemFailures``
means "all of these are done"; returning the failed identifiers means "retry
exactly these". Returning nothing, or raising, means "retry all of them" -- and
a batch that fails wholesale because one record in it was malformed will
republish every healthy event beside it on every redelivery, for as long as the
bad record survives. That is the defect this shape exists to prevent, and it is
what ``test_one_bad_record_does_not_fail_the_whole_batch`` holds in place.

A genuine bus fault is the one case where failing the whole batch is right:
nothing was published, there is nothing to report per entry, and everything
should be retried. So it is allowed to propagate rather than being converted
into a list of per-item failures that would claim more knowledge than we have.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, TypedDict

from services.application.outbox import OutboxPublisher

#: The partition prefix WP-08 writes outbox rows under. The event source
#: mapping should filter on it too; this is the second line, because a filter is
#: configuration and configuration drifts.
OUTBOX_PREFIX: Final = "OUTBOX#"

#: A removed row has nothing left to publish, and the use case would skip it
#: anyway. Named rather than inferred so the reason is readable.
IGNORED_EVENT_NAMES: Final = frozenset({"REMOVE"})


class ItemFailure(TypedDict):
    itemIdentifier: str


class BatchResponse(TypedDict):
    batchItemFailures: list[ItemFailure]


@dataclass(frozen=True, slots=True)
class Delivery:
    """One stream record that named a readable outbox row.

    ``identifier`` is what Lambda retries by; ``event_id`` is what the use case
    publishes by. They are kept apart because several records can name the same
    event, and every one of them has to be answered.
    """

    identifier: str
    event_id: str


@dataclass(frozen=True, slots=True)
class StreamBatch:
    deliveries: tuple[Delivery, ...] = ()
    #: Records that were plainly ours and plainly unusable. Reported as failures
    #: so they are retried and then sent to a dead-letter queue, rather than
    #: dropped silently -- a lost outbox event has no other trace.
    unreadable: tuple[str, ...] = ()


def parse_stream_batch(event: Mapping[str, Any]) -> StreamBatch:
    """Pick the outbox rows out of a stream batch, keeping their identifiers."""
    deliveries: list[Delivery] = []
    unreadable: list[str] = []
    for record in event.get("Records", []):
        if not isinstance(record, Mapping):
            continue
        stream = record.get("dynamodb")
        identifier = _identifier(record, stream)
        if identifier is None:
            # Unidentifiable, so unreportable: naming it in the reply is
            # impossible and inventing an identifier would retry the wrong item.
            continue
        if record.get("eventName") in IGNORED_EVENT_NAMES:
            continue
        partition = _partition(stream)
        if partition is None or not partition.startswith(OUTBOX_PREFIX):
            # Not an outbox row. The stream filter should have excluded it; if
            # it did not, it is still not this worker's to fail over.
            continue
        event_id = partition[len(OUTBOX_PREFIX) :]
        if not event_id:
            unreadable.append(identifier)
            continue
        deliveries.append(Delivery(identifier=identifier, event_id=event_id))
    return StreamBatch(tuple(deliveries), tuple(unreadable))


def _identifier(record: Mapping[str, Any], stream: object) -> str | None:
    if isinstance(stream, Mapping):
        sequence = stream.get("SequenceNumber")
        if isinstance(sequence, str) and sequence:
            return sequence
    fallback = record.get("eventID")
    return fallback if isinstance(fallback, str) and fallback else None


def _partition(stream: object) -> str | None:
    if not isinstance(stream, Mapping):
        return None
    keys = stream.get("Keys")
    if not isinstance(keys, Mapping):
        return None
    partition = keys.get("pk")
    if not isinstance(partition, Mapping):
        return None
    value = partition.get("S")
    return value if isinstance(value, str) else None


def batch_response(failures: Sequence[str]) -> BatchResponse:
    """Render the reply, deduplicated and in the order the records arrived."""
    seen: set[str] = set()
    ordered: list[ItemFailure] = []
    for identifier in failures:
        if identifier in seen:
            continue
        seen.add(identifier)
        ordered.append({"itemIdentifier": identifier})
    return {"batchItemFailures": ordered}


def create_outbox_handler(
    publisher: OutboxPublisher,
) -> Callable[[Mapping[str, Any], object], BatchResponse]:
    """Compose a testable handler around an already-built use case."""

    def handle(event: Mapping[str, Any], _context: object) -> BatchResponse:
        batch = parse_stream_batch(event)
        outcome = publisher.publish([delivery.event_id for delivery in batch.deliveries])
        failed = set(outcome.failed)
        return batch_response(
            [delivery.identifier for delivery in batch.deliveries if delivery.event_id in failed]
            + list(batch.unreadable)
        )

    return handle


def lambda_handler(event: Mapping[str, Any], context: object) -> BatchResponse:
    """Production composition root for the publisher."""
    from services.adapters.composition import build_event_bus, build_state_store

    publisher = OutboxPublisher(store=build_state_store(), bus=build_event_bus())
    return create_outbox_handler(publisher)(event, context)


__all__ = [
    "IGNORED_EVENT_NAMES",
    "OUTBOX_PREFIX",
    "BatchResponse",
    "Delivery",
    "ItemFailure",
    "StreamBatch",
    "batch_response",
    "create_outbox_handler",
    "lambda_handler",
    "parse_stream_batch",
]
