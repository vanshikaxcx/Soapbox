"""The queue end of the loop: an event becomes a running execution (WP-07).

This is the piece that was missing. Stage 2 committed and published; Stage 3
could start and repair; nothing joined them, so there was no path from a
committed outbox row to a run at all.

The handler is transport and nothing else. It reads an SQS batch, unwraps the
EventBridge envelope each message carries, validates the detail as the
``OutboxEvent`` WP-08 committed, and asks the controller to resolve it. Every
decision about what that means belongs upstairs.

**Identifiers are SQS's, not the stream's.** ``itemIdentifier`` here is the
``messageId``. The publisher's reply uses a DynamoDB Streams ``SequenceNumber``,
because Streams retries by position in a shard and SQS retries by message. They
are both strings and neither transport validates the other's, so conflating
them would retry the wrong thing -- or nothing -- with no error to show for it.

**There is no deduplication here, deliberately.** At-least-once delivery means
this handler will see the same event again, and the answer is already built: the
execution is named ``job_id-rN`` and only a retry changes ``N``, so a repeat
delivery resolves to the run that exists. A second mechanism would not add a
guarantee, only a second thing to get wrong -- and the two could disagree.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from pydantic import ValidationError

from services.application.controller import JobController
from services.application.outbox import job_id_of
from services.domain.errors import DomainError
from services.domain.jobs import OutboxEvent


class ItemFailure(TypedDict):
    itemIdentifier: str


class BatchResponse(TypedDict):
    batchItemFailures: list[ItemFailure]


@dataclass(frozen=True, slots=True)
class Message:
    """One queued event, and the id SQS will retry it by."""

    message_id: str
    job_id: str


@dataclass(frozen=True, slots=True)
class QueueBatch:
    messages: tuple[Message, ...] = ()
    #: Messages that were plainly addressed to us and plainly unusable.
    #:
    #: These are reported as failures, exactly like a message whose job is
    #: missing, and the two are *not* given different answers. It is tempting to
    #: give them one -- a body that will never parse cannot be improved by
    #: redelivery, so retrying it only delays the dead-letter queue, whereas a
    #: job that is not visible yet is precisely what redelivery is for.
    #:
    #: But SQS offers no third answer. A partial-batch reply can say "done with
    #: this" or "send it again"; there is no "dead-letter this now". Done-with-it
    #: deletes the message, so choosing it for an unparseable body would destroy
    #: a committed command and leave no trace of it anywhere -- the exact loss
    #: this reply shape exists to prevent. Reporting it costs a bounded handful
    #: of redeliveries, capped by ``maxReceiveCount``, and then it lands in the
    #: dead-letter queue where somebody can look at it.
    #:
    #: The distinction is still worth keeping, so it is kept *structurally*: an
    #: unusable message is on this field rather than mixed into ``messages``, so
    #: the DLQ replay that Stage 5 builds can tell "this will never parse" from
    #: "this was transient" without having to work it out again.
    unreadable: tuple[str, ...] = ()


def parse_queue_batch(event: Mapping[str, Any]) -> QueueBatch:
    """Pull the job ids out of an SQS batch, keeping their message ids."""
    messages: list[Message] = []
    unreadable: list[str] = []
    for record in event.get("Records", []):
        if not isinstance(record, Mapping):
            continue
        message_id = record.get("messageId")
        if not isinstance(message_id, str) or not message_id:
            # Unidentifiable, so unreportable: naming it in the reply is
            # impossible, and inventing an id would retry a different message.
            continue
        outbox_event = _event_in(record.get("body"))
        if outbox_event is None:
            unreadable.append(message_id)
            continue
        messages.append(Message(message_id=message_id, job_id=job_id_of(outbox_event)))
    return QueueBatch(tuple(messages), tuple(unreadable))


def _event_in(body: object) -> OutboxEvent | None:
    """The committed event inside an EventBridge envelope, or ``None``.

    Validated as the domain's own ``OutboxEvent`` rather than picked apart field
    by field. The envelope is data that has been through two services by the
    time it arrives, and a detail that does not reproduce the record WP-08
    committed is not something to act on half-understood.

    Validated *from JSON*, which is not a detail. ``Record`` sets
    ``strict=True``, so ``model_validate`` on an already-parsed dict refuses the
    ISO string that ``occurred_at`` arrives as -- correctly, because in Python a
    ``str`` is not a ``datetime``. Pydantic allows that conversion only when it
    can see the value came from JSON, so the detail is re-encoded and handed
    back as text. The same rule is why the DynamoDB adapter stores record
    bodies as JSON instead of mapped attributes.
    """
    if not isinstance(body, str):
        return None
    try:
        envelope = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(envelope, Mapping):
        return None
    detail = envelope.get("detail")
    if not isinstance(detail, Mapping):
        return None
    try:
        return OutboxEvent.model_validate_json(json.dumps(dict(detail)))
    except (ValidationError, TypeError, ValueError):
        return None


def batch_response(failures: Sequence[str]) -> BatchResponse:
    """Render the reply, deduplicated and in the order the messages arrived."""
    seen: set[str] = set()
    ordered: list[ItemFailure] = []
    for identifier in failures:
        if identifier in seen:
            continue
        seen.add(identifier)
        ordered.append({"itemIdentifier": identifier})
    return {"batchItemFailures": ordered}


def create_job_consumer(
    controller: JobController,
) -> Callable[[Mapping[str, Any], object], BatchResponse]:
    """Compose a testable handler around an already-built controller."""

    def handle(event: Mapping[str, Any], _context: object) -> BatchResponse:
        batch = parse_queue_batch(event)
        failures: list[str] = []
        for message in batch.messages:
            if not _resolved(controller, message):
                failures.append(message.message_id)
        return batch_response(failures + list(batch.unreadable))

    return handle


def _resolved(controller: JobController, message: Message) -> bool:
    """Whether this message is done with, or should come back.

    A fault is caught per message rather than allowed to end the batch. That is
    the opposite of the publisher, and deliberately so: the publisher hands a
    whole batch to the bus in one call, so a fault there has no single owning
    message and nothing to report per entry. Here ``deliver`` is called once per
    message, so a fault does have an owner -- and reporting only the owner is
    the entire reason SQS offers a partial-batch reply.

    A total engine outage still retries everything, because then every message
    gets its own fault. The batch is never lost; it is just never lost *as a
    batch*.
    """
    try:
        outcome = controller.deliver(message.job_id)
    except Exception:
        return False
    # A ``DomainError`` here is not a shrug. ``JobNotFound`` in particular means
    # the job row is missing for an event that was committed in the same
    # transaction as that row -- so it cannot be a race, and a retry will not
    # invent it. Reporting it sends the message to the dead-letter queue, where
    # it is visible; treating it as success would delete the only evidence.
    return not isinstance(outcome, DomainError)


def lambda_handler(event: Mapping[str, Any], context: object) -> BatchResponse:
    """Production composition root for the consumer."""
    from services.adapters.composition import build_state_store, build_workflow_engine

    controller = JobController(store=build_state_store(), engine=build_workflow_engine())
    return create_job_consumer(controller)(event, context)


__all__ = [
    "BatchResponse",
    "ItemFailure",
    "Message",
    "QueueBatch",
    "batch_response",
    "create_job_consumer",
    "lambda_handler",
    "parse_queue_batch",
]
