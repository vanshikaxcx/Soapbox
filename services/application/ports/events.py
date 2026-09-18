"""The event bus, as the publisher needs it (WP-07).

A separate port from ``StateStore`` because the two fail differently and the
publisher has to tell the difference. A store rejects a write because someone
else got there first; a bus rejects an *entry* while accepting the rest of the
call, and the caller's only correct response is to retry that one entry.

So ``publish`` returns the entries the bus refused rather than raising. A bus
that raised on a partial rejection would leave the caller unable to say which
of ten events landed -- and republishing all ten because one failed is how
at-least-once turns into an avalanche. Publication is at-least-once by design:
the outbox row is committed with the state change, so the publisher's job is to
catch up, never to decide, and duplicate suppression belongs to the consumer.

A genuine fault -- no credentials, no network, a bus that does not exist -- is
still an exception. It is not a per-entry outcome and there is nothing to
report about individual events, so the whole batch has to be retried.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable

from services.domain.errors import DomainError
from services.domain.ids import Id
from services.domain.jobs import OutboxEvent


@dataclass(frozen=True, slots=True)
class PublishRejected(DomainError):
    """One entry the bus refused, while accepting the others in the same call.

    Carries the bus's own error code rather than prose, because an operator
    reading a retry loop needs to tell a throttle apart from a malformed entry:
    the first will succeed on its own, the second never will.
    """

    code: ClassVar[str] = "publish_rejected"
    event_id: Id
    error_code: str


@runtime_checkable
class EventBus(Protocol):
    """Where a committed outbox row goes. EventBridge in production."""

    def publish(self, events: Sequence[OutboxEvent]) -> list[PublishRejected]:
        """Publish a batch, and report only the entries that were refused.

        An empty list means every event was accepted. The implementation is
        responsible for whatever batching the transport requires; the caller
        hands over the events it has and does not count them.
        """
        ...


__all__ = ["EventBus", "PublishRejected"]
