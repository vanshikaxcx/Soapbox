"""Resolving a job to an execution, and reconciling one that went quiet (WP-07).

Three rules run through everything here, and none of them is this module's to
invent -- ``services/domain/jobs.py`` owns every job transition, and this only
decides *which* one to ask for.

**A duplicate delivery resolves; it never starts a second run.** The execution
is named ``job_id-rN`` and only a retry changes ``N``, so the same delivery
arriving twice names the same execution. The suppression is the name, which is
why it cannot be forgotten. ``resolve_delivery()`` states the same rule for a
job that is already past ``queued``, and it is called rather than reimplemented.

**A retry is a new execution; a replay is the existing one.** ``retry()``
increments the generation, which changes the name, which is what makes the new
run distinct while leaving every business identity -- payment key, order key --
alone. A replay re-delivers an event and must land on the run that already
exists. If a replay ever produced a new generation, that is the bug this
distinction is here to catch, and there is a test in each direction.

**"We stopped watching" is not "it failed".** Repair asks the engine what became
of an execution and moves the job to match. It has exactly one answer for "the
engine does not know": leave the job running. A job marked failed because a
heartbeat went quiet is a job failure invented by the watcher, and WP-02's
copy exists precisely because a job failure says nothing about money.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import ClassVar, Final

from services.application.ports import (
    ExecutionState,
    StateStore,
    WorkflowEngine,
    Write,
    read,
)
from services.application.purchase import job_key
from services.domain import jobs
from services.domain.canonical import canonical_json
from services.domain.errors import DomainError, IllegalTransition
from services.domain.ids import Id
from services.domain.jobs import Job, resolve_delivery
from services.domain.transitions import JobState

#: How many generations a job may reach before an operator has to look at it.
#: A cap, not a rule: ``retry()`` is still the only thing that increments a
#: generation, and this only decides whether to ask it to.
DEFAULT_MAX_GENERATIONS: Final = 3

#: How long a ``running`` job may go without finishing before repair considers
#: it worth asking the engine about. Not a failure threshold -- passing it means
#: "look", never "give up".
DEFAULT_STALE_AFTER_SECONDS: Final = 900

#: Recorded on a job whose execution the engine reports as timed out. Named so
#: an operator reads a cause instead of inferring one from a silence.
TIMED_OUT_CODE: Final = "execution_timed_out"
ABORTED_CODE: Final = "execution_aborted"
FAILED_CODE: Final = "execution_failed"

_ERROR_CODES: Final = {
    ExecutionState.FAILED: FAILED_CODE,
    ExecutionState.TIMED_OUT: TIMED_OUT_CODE,
    ExecutionState.ABORTED: ABORTED_CODE,
}


@dataclass(frozen=True, slots=True)
class JobNotFound(DomainError):
    """No such job row. Returned, not raised: a replay of a pruned job is a
    normal thing to receive and not something a caller should crash on.
    """

    code: ClassVar[str] = "job_not_found"
    job_id: Id


@dataclass(frozen=True, slots=True)
class RetryCapReached(DomainError):
    """The job has been retried as often as it is allowed to be.

    Carries the generation reached *and* the cap, so an operator sees why it
    stopped rather than inferring it from a number with nothing to compare to.
    """

    code: ClassVar[str] = "retry_cap_reached"
    job_id: Id
    generation: int
    cap: int


@dataclass(frozen=True, slots=True)
class JobResolved:
    """The run this delivery resolved to.

    ``started_new_run`` is the observable form of "duplicate delivery produces
    exactly one run": a second delivery of the same event reports ``False`` and
    the run count does not move.
    """

    job_id: str
    run_id: str
    execution_ref: str | None
    started_new_run: bool


class RepairAction(StrEnum):
    """What repair did, named rather than inferred from the resulting status."""

    NOT_RUNNING = "not_running"
    STILL_RUNNING = "still_running"
    NEVER_STARTED = "never_started"
    UNKNOWN_TO_THE_ENGINE = "unknown_to_the_engine"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Repaired:
    job_id: str
    action: RepairAction
    status: JobState


def execution_payload(job: Job) -> str:
    """What the workflow is started with.

    Built from the job's identity and never from its status. The input has to be
    byte-identical across deliveries, because Step Functions answers a re-start
    with identical input by handing back the existing execution, and one with
    *different* input by raising. A payload carrying ``status`` or
    ``execution_ref`` would change the instant the first start succeeded, so
    every ordinary duplicate would take the error path instead of the quiet one.

    Canonical JSON rather than ``model_dump_json`` for the same reason: sorted
    keys and fixed separators, so the bytes do not depend on field order.
    """
    return canonical_json(
        {
            "job_id": job.job_id,
            "owner_id": job.owner_id,
            "job_type": job.job_type.value,
            "generation": job.generation,
            "input_hash": job.input_hash,
            "reference": job.reference,
        }
    ).decode("utf-8")


@dataclass(frozen=True, slots=True)
class JobController:
    """Starts jobs, retries them within a cap, and repairs the ones that stop."""

    store: StateStore
    engine: WorkflowEngine
    max_generations: int = DEFAULT_MAX_GENERATIONS
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS

    # -- starting ----------------------------------------------------------

    def deliver(self, job_id: str) -> JobResolved | DomainError:
        """Resolve one delivery of a job to its execution, starting it if new."""
        job = self._job(job_id)
        if job is None:
            return JobNotFound(job_id=job_id)
        if job.status is not JobState.QUEUED:
            # Already running, or finished. The domain says what a repeat
            # delivery means, and it says the same thing for a failed job as for
            # a running one: resolve, never revive.
            delivery = resolve_delivery(job)
            return JobResolved(
                job_id=job.job_id,
                run_id=delivery.run_id,
                execution_ref=job.execution_ref,
                started_new_run=delivery.started_new_run,
            )
        return self._start(job)

    def _start(self, job: Job) -> JobResolved | DomainError:
        execution = self.engine.start(run_id=job.run_id, payload=execution_payload(job))
        started = jobs.start(job, execution.execution_ref)
        if isinstance(started, IllegalTransition):
            return started
        self._persist(started, "the job is running under a named execution")
        return JobResolved(
            job_id=job.job_id,
            run_id=execution.run_id,
            execution_ref=execution.execution_ref,
            started_new_run=execution.started_new_run,
        )

    # -- retrying ----------------------------------------------------------

    def retry(self, job_id: str) -> JobResolved | DomainError:
        """An authorised retry: a new generation, and therefore a new run."""
        job = self._job(job_id)
        if job is None:
            return JobNotFound(job_id=job_id)
        if job.generation >= self.max_generations:
            return RetryCapReached(
                job_id=job.job_id, generation=job.generation, cap=self.max_generations
            )
        retried = jobs.retry(job)
        if isinstance(retried, IllegalTransition):
            return retried
        self._persist(retried, "an authorised retry, one generation on")
        return self._start(retried)

    # -- repairing ---------------------------------------------------------

    def stale_running(self, now: datetime) -> list[str]:
        """Running jobs whose *current run* has been going long enough to ask about.

        Measured from when the execution started, not from when the job was
        created. Those are different numbers the moment anything is retried:
        ``retry()`` increments the generation and starts a new execution but
        leaves ``created_at`` alone, so a job retried one second ago has an
        ancient creation date and a brand-new run. Measuring from the job would
        put it on this list immediately and keep it there -- the list would fill
        with exactly the jobs somebody had just intervened on.

        Falls back to ``created_at`` when the engine does not report a start
        time, or when the job has no execution recorded at all. That case is a
        job that is running with nothing to ask about, which is worth surfacing
        rather than hiding behind a missing timestamp.

        One engine call per running job, which O-3 permits here: repair is
        operator-and-schedule work on no shopper-facing path. Being on this list
        is not a finding -- it is the reason to go and look.
        """
        cutoff = now - timedelta(seconds=self.stale_after_seconds)
        stale: list[str] = []
        for key in self.store.keys_matching("JOB#"):
            job = read(self.store, key, Job)
            if job is None or job.status is not JobState.RUNNING:
                continue
            if self._running_since(job) <= cutoff:
                stale.append(job.job_id)
        return stale

    def _running_since(self, job: Job) -> datetime:
        """When the run now in progress began, as well as can be known."""
        if job.execution_ref is None:
            return job.created_at
        status = self.engine.status(execution_ref=job.execution_ref)
        if status is None or status.started_at is None:
            return job.created_at
        return status.started_at

    def repair(self, job_id: str) -> Repaired | DomainError:
        """Reconcile one job against what the engine says actually happened."""
        job = self._job(job_id)
        if job is None:
            return JobNotFound(job_id=job_id)
        if job.status is not JobState.RUNNING:
            return Repaired(job.job_id, RepairAction.NOT_RUNNING, job.status)
        if job.execution_ref is None:
            # Running with no execution recorded: the crash landed between the
            # start and the write. There is nothing to ask about, and inventing
            # a failure here would report a job dead that may well be running.
            return Repaired(job.job_id, RepairAction.NEVER_STARTED, job.status)

        status = self.engine.status(execution_ref=job.execution_ref)
        if status is None:
            # The engine has no record of it. That is not a failure; it is an
            # absence of information, and the two lead to opposite actions.
            return Repaired(job.job_id, RepairAction.UNKNOWN_TO_THE_ENGINE, job.status)
        if status.state is ExecutionState.RUNNING:
            # Quiet is not dead. However long it has been, the engine says this
            # run is alive, and that outranks a stale heartbeat every time.
            return Repaired(job.job_id, RepairAction.STILL_RUNNING, job.status)
        if status.state is ExecutionState.SUCCEEDED:
            return self._settle(job, jobs.succeed(job, status.result_ref), RepairAction.SUCCEEDED)
        return self._settle(
            job,
            jobs.fail(job, status.error_code or _ERROR_CODES.get(status.state, FAILED_CODE)),
            RepairAction.FAILED,
        )

    def _settle(
        self, job: Job, transition: Job | IllegalTransition, action: RepairAction
    ) -> Repaired | DomainError:
        if isinstance(transition, IllegalTransition):
            return transition
        self._persist(transition, "the engine's answer, recorded on the job")
        return Repaired(job.job_id, action, transition.status)

    # -- internals ---------------------------------------------------------

    def _job(self, job_id: str) -> Job | None:
        return read(self.store, job_key(job_id), Job)

    def _persist(self, job: Job, reason: str) -> None:
        """Write the job row back.

        Unconditional, because ``Job`` carries no version to compare against.
        That is survivable here and nowhere else: two controllers racing to
        record the same transition write the same row, and the thing that stops
        them producing two *runs* is the execution name, not this write.
        """
        self.store.transact([Write(key=job_key(job.job_id), item=job, reason=reason)])


__all__ = [
    "ABORTED_CODE",
    "DEFAULT_MAX_GENERATIONS",
    "DEFAULT_STALE_AFTER_SECONDS",
    "FAILED_CODE",
    "TIMED_OUT_CODE",
    "JobController",
    "JobNotFound",
    "JobResolved",
    "Repaired",
    "RepairAction",
    "RetryCapReached",
    "execution_payload",
]
