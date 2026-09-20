"""Operator actions, and the record each one leaves (WP-07).

Two actions an operator can take when something has stopped: retry a job, and
replay an event that was published but never took effect. The spec requires both
to be operator-invocable *and* to leave an audit record, and the second half is
the one that gets forgotten -- an operator action that leaves no trace is
indistinguishable afterwards from the system having done it by itself.

**A retry goes through the controller, never around it.** ``jobs.retry()`` is
right there and calling it directly would be shorter by four lines; it would
also skip the cap, which is the only thing standing between a wedged job and an
unbounded retry loop with a human's name on it. The controller is where the cap
lives, so the controller is what an operator talks to.

**A replay re-delivers; it never re-decides.** The event is republished exactly
as it was committed. The generation does not move, so the execution name does
not move, so the consumer resolves to the run that already exists. If a replay
ever produced a new generation it would produce a new name, and the duplicate
suppression the whole design rests on would be bypassed by the very tool meant
to recover from a duplicate. There is a test in those words.

**The operator is checked before anything acts.** This used to be wrong, and
wrong in the worst direction: the id was validated when the audit record was
constructed, which is *after* the retry. A typo'd ``--operator`` retried the
job, started an execution, wrote no audit row, and printed "refused before
acting". Three typos reached the retry cap having recorded nothing at all.
Validation now happens on the first line of each action, before the controller
is touched, so a refusal is a refusal and the audit trail cannot be outrun by
the thing it exists to describe.

**When the record is written.** After the action, carrying its outcome, because
an audit entry that says "retried" for a retry that was refused is worse than no
entry at all -- it is a false one, and an operator reading it later has no way to
tell. The cost is the crash window: a process that dies between acting and
recording leaves an action with no record. That is the lesser harm, and it is
narrow, but it is real and it is written down here rather than discovered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import Field

from services.application.controller import JobController, RetryCapReached
from services.application.outbox import outbox_key
from services.application.ports import (
    Clock,
    Condition,
    EventBus,
    IdFactory,
    Key,
    StateStore,
    Write,
    read,
)
from services.domain.errors import DomainError
from services.domain.ids import ID_PATTERN, Id, Timestamped, is_valid_id
from services.domain.jobs import OutboxEvent

#: The audit trail's own partition. Operator actions are not aggregate state --
#: they are a record *about* the system rather than part of it -- so they live
#: under their own prefix and never inside a purchase.
AUDIT_PREFIX = "OPERATION#"


def audit_key(operation_id: str) -> Key:
    return (f"{AUDIT_PREFIX}{operation_id}", "RECORD")


class OperatorNotNamed(ValueError):
    """The operator id is not one this system can record.

    Raised *before* anything acts, which is the entire point. An audit trail
    that can be outrun by the action it describes is not an audit trail, and the
    one moment there is to catch a mistyped name is before the retry, not while
    writing it down afterwards.
    """


class AuditNotRecorded(RuntimeError):
    """The action was taken and the record of it could not be written.

    Raised rather than returned, and raised loudly, because the caller is about
    to be handed an ``AuditRecord`` describing something that happened and was
    never written down. In a module whose whole premise is that an unrecorded
    action is indistinguishable from the system acting alone, quietly returning
    that record would be the failure this file exists to prevent.
    """


class OperatorAction(StrEnum):
    RETRY_JOB = "retry_job"
    REPLAY_EVENT = "replay_event"


class Outcome(StrEnum):
    """What the action actually did, in the operator's own vocabulary.

    Distinct from the domain's error codes on purpose: an operator is asking
    "did my intervention take effect", which is a different question from "what
    did the rule say", and flattening the two loses the one they asked.
    """

    DONE = "done"
    REFUSED_BY_THE_CAP = "refused_by_the_cap"
    REFUSED_BY_THE_RULES = "refused_by_the_rules"
    NOTHING_TO_ACT_ON = "nothing_to_act_on"
    REJECTED_BY_THE_BUS = "rejected_by_the_bus"


class AuditRecord(Timestamped):
    """One operator action, after the fact, with what it did."""

    operation_id: Id
    action: OperatorAction
    #: Who asked. Never derived from the process or the environment: an audit
    #: trail whose actor is "whoever had the credentials" answers nothing.
    operator_id: Id
    #: The job or event acted on.
    subject: str = Field(min_length=1, max_length=256)
    outcome: Outcome
    #: The rule's own code when it refused, so the audit and the domain agree.
    detail: str | None = None
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class OperatorConsole:
    """What an operator script is allowed to do, and nothing more.

    Deliberately small. Every method here is reachable by a human with
    production credentials, so the surface is the blast radius.
    """

    store: StateStore
    controller: JobController
    bus: EventBus
    clock: Clock
    ids: IdFactory

    def retry_job(self, *, operator_id: str, job_id: str) -> AuditRecord:
        """Ask the controller for an authorised retry, and record the answer."""
        self._require_a_named_operator(operator_id)
        result = self.controller.retry(job_id)
        if isinstance(result, RetryCapReached):
            return self._record(
                OperatorAction.RETRY_JOB,
                operator_id,
                job_id,
                Outcome.REFUSED_BY_THE_CAP,
                f"generation {result.generation} of {result.cap}",
            )
        if isinstance(result, DomainError):
            return self._record(
                OperatorAction.RETRY_JOB,
                operator_id,
                job_id,
                Outcome.REFUSED_BY_THE_RULES,
                result.code,
            )
        return self._record(
            OperatorAction.RETRY_JOB, operator_id, job_id, Outcome.DONE, result.run_id
        )

    def replay_event(self, *, operator_id: str, event_id: str) -> AuditRecord:
        """Put a committed event back on the bus, exactly as it was committed.

        Republished even though the row already says ``published``, because that
        is the whole point: the row records that we *sent* it, and a replay
        exists for the times when sending was not the same as arriving. The row
        is not rewritten -- a replay changes nothing about what was decided, and
        a publication state that went backwards would make the ordinary
        publisher send it a third time.
        """
        self._require_a_named_operator(operator_id)
        event = read(self.store, outbox_key(event_id), OutboxEvent)
        if event is None:
            return self._record(
                OperatorAction.REPLAY_EVENT,
                operator_id,
                event_id,
                Outcome.NOTHING_TO_ACT_ON,
                "no such outbox row",
            )
        rejected = self.bus.publish([event])
        if rejected:
            return self._record(
                OperatorAction.REPLAY_EVENT,
                operator_id,
                event_id,
                Outcome.REJECTED_BY_THE_BUS,
                rejected[0].error_code,
            )
        return self._record(
            OperatorAction.REPLAY_EVENT,
            operator_id,
            event_id,
            Outcome.DONE,
            event.reference,
        )

    def history(self) -> list[AuditRecord]:
        """Every operator action recorded, oldest key first.

        A scan, which O-3 permits: this is operator-only, bounded by how often a
        human intervenes, and on no shopper-facing path.
        """
        records = []
        for key in self.store.keys_matching(AUDIT_PREFIX):
            record = read(self.store, key, AuditRecord)
            if record is not None:
                records.append(record)
        # Sorted by when it happened, not by key. The key carries a generated
        # id, so key order is whatever the id factory felt like -- which reads
        # as chronological under the sequential ids used in tests and is
        # arbitrary under the real ones. An audit trail out of order is worse
        # than useless: it invites a conclusion about cause.
        return sorted(records, key=lambda record: record.recorded_at)

    def _require_a_named_operator(self, operator_id: str) -> None:
        """Refuse before acting, using the identifier rule the codebase has.

        ``is_valid_id`` rather than a rule invented here: an operator id is an
        identifier like any other, and a second spelling of "what an id is"
        would be a second thing to keep in step.
        """
        if not is_valid_id(operator_id):
            raise OperatorNotNamed(
                f"operator id {operator_id!r} does not match {ID_PATTERN}; nothing has been done"
            )

    def _record(
        self,
        action: OperatorAction,
        operator_id: str,
        subject: str,
        outcome: Outcome,
        detail: str | None,
    ) -> AuditRecord:
        record = AuditRecord(
            operation_id=self.ids.new_id("operation"),
            action=action,
            operator_id=operator_id,
            subject=subject,
            outcome=outcome,
            detail=detail,
            recorded_at=self.clock.now(),
        )
        refused = self.store.transact(
            [
                Write(
                    key=audit_key(record.operation_id),
                    item=record,
                    condition=Condition.MUST_NOT_EXIST,
                    reason="an operator action is recorded once",
                )
            ]
        )
        if refused is not None:
            raise AuditNotRecorded(
                f"{action.value} on {subject} was carried out and its record was "
                f"refused at {refused.key}: {refused.reason}"
            )
        return record


__all__ = [
    "AUDIT_PREFIX",
    "AuditNotRecorded",
    "AuditRecord",
    "OperatorAction",
    "OperatorConsole",
    "OperatorNotNamed",
    "Outcome",
    "audit_key",
]
