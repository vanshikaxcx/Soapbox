"""Publishing committed outbox rows (WP-07).

The row was written inside the transaction that changed the state it describes,
so by the time this runs the decision has already been made and committed. That
is the whole point of an outbox: **the publisher catches up, it never decides.**
Nothing here inspects an event to work out whether it should have happened, and
nothing here writes a row that did not already exist.

Two consequences follow, and both are load-bearing:

* **Publication is at-least-once.** A crash between the bus accepting an event
  and the row being marked published leaves the row pending, and the next
  delivery publishes it again. That is correct, not a leak: suppressing the
  duplicate here would require this module to remember what it had done, which
  is exactly the durable state the outbox already is. The consumer deduplicates.
* **One event's failure is one event's failure.** The batch is reported entry by
  entry, because a whole-batch retry caused by a single malformed event
  republishes every healthy event beside it, forever, at whatever rate the
  source redelivers.

The events are re-read from the store rather than taken from whatever delivered
them. A stream record is a snapshot of a moment; the row is the truth now, and
re-reading is what makes a replayed delivery resolve to the current state
instead of resurrecting an old one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from services.application.ports import (
    ConditionFailed,
    EventBus,
    PublishRejected,
    StateStore,
    Write,
    read,
)

# The key is WP-08's -- the row is written inside its approval transaction --
# so it is imported rather than restated. A publisher carrying its own copy of
# a key prefix is a silent break waiting for the day one of them changes.
from services.application.purchase import outbox_key
from services.domain.jobs import OutboxEvent, PublicationState


def job_id_of(event: OutboxEvent) -> str:
    """The job this outbox event dispatches.

    WP-08 writes ``reference=job_id`` on every outbox event it commits, at both
    construction sites. Named here rather than read inline at the call site,
    because ``reference`` means something *different* on the two envelopes that
    carry it: on ``OutboxEvent`` it is the job to run, and on ``Job`` it is the
    aggregate the job is about -- a purchase id, or an attempt id.

    A reader who knows one meaning will guess the other wrong, and the guess is
    silent: routing on ``Job.reference`` would look up a job that does not
    exist and the event would be dead-lettered rather than run. So the mapping
    has one home and a test that pins it against WP-08's own output.
    """
    return event.reference


@dataclass(frozen=True, slots=True)
class PublicationOutcome:
    """What happened to each event, named so a caller never has to infer it.

    ``skipped`` is deliberately not ``failed``. An event that was already
    published, or whose row has gone, is not something a retry can improve --
    reporting it as a failure would make the source redeliver it forever.
    """

    published: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OutboxPublisher:
    """Reads committed outbox rows and puts them on the bus."""

    store: StateStore
    bus: EventBus

    def publish(self, event_ids: Sequence[str]) -> PublicationOutcome:
        """Publish every pending event named, and say what became of each."""
        pending: list[OutboxEvent] = []
        skipped: list[str] = []
        seen: set[str] = set()

        for event_id in event_ids:
            if event_id in seen:
                continue
            seen.add(event_id)
            event = read(self.store, outbox_key(event_id), OutboxEvent)
            if event is None or event.publication_state is PublicationState.PUBLISHED:
                # A row that is gone, or already published, has nothing left to
                # do. Not a failure: there is no retry that would change it.
                skipped.append(event_id)
                continue
            pending.append(event)

        if not pending:
            return PublicationOutcome(skipped=tuple(skipped))

        rejected = {rejection.event_id: rejection for rejection in self.bus.publish(pending)}
        published: list[str] = []
        failed: list[str] = []
        for event in pending:
            if event.event_id in rejected:
                failed.append(event.event_id)
                continue
            if self._mark_published(event) is None:
                published.append(event.event_id)
            else:
                failed.append(event.event_id)
        return PublicationOutcome(tuple(published), tuple(failed), tuple(skipped))

    def _mark_published(self, event: OutboxEvent) -> ConditionFailed | None:
        """Record the publication, unconditionally.

        Unconditional because ``OutboxEvent`` carries no version to compare and
        because losing this write is survivable: the row stays pending and the
        event is published again, which at-least-once already allows. A failure
        here is still reported, so the source redelivers and the mark is retried
        -- an unmarked row that nothing retries would be published exactly once
        and then look pending forever.
        """
        return self.store.transact(
            [
                Write(
                    key=outbox_key(event.event_id),
                    item=event.model_copy(update={"publication_state": PublicationState.PUBLISHED}),
                    reason="the event has reached the bus",
                )
            ]
        )


__all__ = [
    "OutboxPublisher",
    "PublicationOutcome",
    "PublishRejected",
    "job_id_of",
    "outbox_key",
]
