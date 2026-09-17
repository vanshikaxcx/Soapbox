"""Job and outbox envelope shapes (WP-02).

The *mechanics* -- Streams, EventBridge, SQS, Step Functions, retry policy -- are
WP-07's. What lives here is the envelope every package has to agree on, and one
rule with teeth: an authorised retry increments ``generation``, and duplicate
delivery never does. That is the difference between "run the work again" and
"there are now two of everything".
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from services.domain.errors import IllegalTransition
from services.domain.ids import Digest, Id, Record, Timestamped
from services.domain.transitions import JobEvent, JobState, apply


class JobType(StrEnum):
    CONVERSE = "converse"
    SPEAK = "speak"
    SEARCH = "search"
    PREPARE = "prepare"
    CHECKOUT = "checkout"
    RECONCILE = "reconcile"
    RECOVERY = "recovery"
    EXPORT = "export"


class PublicationState(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"


class Job(Timestamped):
    job_id: Id
    owner_id: Id
    job_type: JobType
    input_hash: Digest
    reference: str = Field(min_length=1, max_length=256)
    status: JobState = JobState.QUEUED
    stage: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    result_ref: str | None = None
    error_code: str | None = None
    generation: int = Field(default=1, ge=1)
    execution_ref: str | None = None
    created_at: datetime

    @property
    def run_id(self) -> str:
        """The generation-specific execution name, ``job_id-rN``.

        Duplicate delivery resolves to this same name and therefore the same run.
        Only a retry changes it, because only a retry changes the generation.
        """
        return f"{self.job_id}-r{self.generation}"


class OutboxEvent(Timestamped):
    """A committed intention to do work, published after the state it describes."""

    event_id: Id
    schema_version: int = Field(default=1, ge=1)
    event_type: str = Field(min_length=1, max_length=128)
    aggregate_id: Id
    aggregate_version: int = Field(ge=1)
    owner_id: Id
    occurred_at: datetime
    reference: str = Field(min_length=1, max_length=256)
    publication_state: PublicationState = PublicationState.PENDING


def retry(job: Job) -> Job | IllegalTransition:
    """Authorised retry of a terminally failed job.

    Increments the generation, which is what makes the new run distinct from the
    failed one while leaving every business identity -- payment key, order key --
    untouched.
    """
    result = apply("job", job.status, JobEvent.RETRY)
    if isinstance(result, IllegalTransition):
        return result
    return job.model_copy(
        update={
            "status": result,
            "generation": job.generation + 1,
            "error_code": None,
            "execution_ref": None,
        }
    )


def start(job: Job, execution_ref: str) -> Job | IllegalTransition:
    result = apply("job", job.status, JobEvent.START)
    if isinstance(result, IllegalTransition):
        return result
    return job.model_copy(update={"status": result, "execution_ref": execution_ref})


def succeed(job: Job, result_ref: str | None = None) -> Job | IllegalTransition:
    result = apply("job", job.status, JobEvent.SUCCEED)
    if isinstance(result, IllegalTransition):
        return result
    return job.model_copy(update={"status": result, "result_ref": result_ref, "progress": 100})


def fail(job: Job, error_code: str) -> Job | IllegalTransition:
    """A job failure. It says nothing whatsoever about a payment."""
    result = apply("job", job.status, JobEvent.FAIL)
    if isinstance(result, IllegalTransition):
        return result
    return job.model_copy(update={"status": result, "error_code": error_code})


class DuplicateDelivery(Record):
    """The answer to 'we received this event again'."""

    run_id: str
    started_new_run: bool = False


def resolve_delivery(job: Job) -> DuplicateDelivery:
    """Duplicate delivery resolves the existing run; it never starts a second one.

    Crucially it does not revive a failed job either: only an authorised retry
    does that, and only by incrementing the generation.
    """
    return DuplicateDelivery(run_id=job.run_id, started_new_run=False)


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "DuplicateDelivery",
    "Job",
    "JobType",
    "OutboxEvent",
    "PublicationState",
    "fail",
    "resolve_delivery",
    "retry",
    "start",
    "succeed",
]
