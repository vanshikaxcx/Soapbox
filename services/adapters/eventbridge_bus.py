"""The EventBridge ``EventBus`` (WP-07).

``PutEvents`` has one property that catches every implementation written from
memory: **a partial failure is a successful call.** The HTTP request returns
200, no exception is raised, and the rejected entries are reported inside the
response as ``FailedEntryCount`` and a per-entry ``ErrorCode``. An adapter that
only checked for an exception would report ten successes for a call in which
three events were refused, and those three would be lost with no trace -- the
outbox rows would be marked published and nothing would ever retry them.

So the response is read entry by entry. The entries come back index-aligned
with the request, which is the only thing tying a rejection to an event, and it
is why the batches are built and read in the same order.

``PutEvents`` also caps a call at ten entries. The cap is handled here rather
than pushed onto the caller: the port promises "hand over the events you have",
and a publisher that had to count to ten would be encoding a transport limit
into a use case.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Final

from services.application.ports import PublishRejected
from services.domain.jobs import OutboxEvent

if TYPE_CHECKING:  # pragma: no cover - import exists for the type checker only
    from mypy_boto3_events.client import EventBridgeClient
    from mypy_boto3_events.type_defs import PutEventsRequestEntryTypeDef

#: EventBridge's own ceiling on one ``PutEvents`` call.
BATCH_LIMIT: Final = 10

#: Reported when the bus refuses an entry without saying why. Reachable: a
#: failed entry is one with no ``EventId``, and nothing obliges EventBridge to
#: put an ``ErrorCode`` beside the absence. Named so a retry loop logs something
#: an operator can search for rather than an empty string.
UNKNOWN_ERROR: Final = "UnknownError"


class EventBridgeBus:
    """Publishes outbox events onto one EventBridge bus.

    ``source`` is fixed per deployment rather than derived from the event,
    because EventBridge rules match on it: a source that varied per event would
    make every rule a moving target. The event's own type is the detail type,
    which is what a rule should be selecting on.
    """

    def __init__(self, *, client: EventBridgeClient, bus_name: str, source: str) -> None:
        self._client = client
        self._bus = bus_name
        self._source = source

    def publish(self, events: Sequence[OutboxEvent]) -> list[PublishRejected]:
        rejected: list[PublishRejected] = []
        for batch in _batched(events, BATCH_LIMIT):
            response = self._client.put_events(Entries=[self._entry(event) for event in batch])
            failed_count = response.get("FailedEntryCount") or 0
            if not failed_count:
                continue
            # Index-aligned with the request, which is the only link back to the
            # event. Zipped strictly so a short response is a loud failure
            # rather than a silent misattribution of somebody else's error.
            #
            # A failure is an entry with no ``EventId``, not an entry with an
            # ``ErrorCode``. Those sound like the same test and are not: an
            # entry the bus refused without saying why has neither, and keying
            # off ``ErrorCode`` dropped it -- reporting success for an event
            # that was never published, so the outbox row would be marked
            # published and nothing would ever retry it. Reading the *absence*
            # of an id means an unexplained refusal is still a refusal.
            found: list[PublishRejected] = []
            for event, result in zip(batch, response.get("Entries", []), strict=True):
                if result.get("EventId"):
                    continue
                found.append(
                    PublishRejected(
                        event_id=event.event_id,
                        error_code=result.get("ErrorCode") or UNKNOWN_ERROR,
                    )
                )
            if len(found) != failed_count:
                # The bus counted its failures and we found a different number.
                # One of the two readings is wrong and there is no way to tell
                # which, so neither is reported: guessing here means either
                # retrying a published event or dropping an unpublished one.
                raise ValueError(
                    f"EventBridge reported {failed_count} failed entries and "
                    f"{len(found)} could be identified; the response cannot be "
                    "attributed to events"
                )
            rejected.extend(found)
        return rejected

    def _entry(self, event: OutboxEvent) -> PutEventsRequestEntryTypeDef:
        return {
            "Source": self._source,
            "DetailType": event.event_type,
            "Detail": event.model_dump_json(),
            "EventBusName": self._bus,
            "Time": event.occurred_at,
            "Resources": [event.aggregate_id],
        }


def _batched(events: Sequence[OutboxEvent], size: int) -> Iterator[Sequence[OutboxEvent]]:
    for start in range(0, len(events), size):
        yield events[start : start + size]


__all__ = ["BATCH_LIMIT", "UNKNOWN_ERROR", "EventBridgeBus"]
