"""What the controller promises about runs, retries and silence (WP-07).

Three groups, each named after the failure it prevents: a duplicate delivery
that starts a second run, a replay that invents a generation, and a watcher that
reports a job dead because it stopped hearing from it.

Every transition here is the domain's. The assertions are about which one the
controller asked for and what it wrote down, never about a rule it invented.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.application.controller import (
    DEFAULT_MAX_GENERATIONS,
    TIMED_OUT_CODE,
    JobController,
    JobNotFound,
    JobResolved,
    RepairAction,
    Repaired,
    RetryCapReached,
    execution_payload,
)
from services.application.fakes import FixedClock, MemoryStore, RecordingWorkflowEngine
from services.application.ports import ExecutionState, Write, read
from services.application.purchase import job_key
from services.domain.errors import IllegalTransition
from services.domain.jobs import Job, JobType
from services.domain.transitions import JobState

MOMENT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
DIGEST = "a" * 64
JOB_ID = "job-0000001"


def job(
    *,
    job_id: str = JOB_ID,
    status: JobState = JobState.QUEUED,
    generation: int = 1,
    execution_ref: str | None = None,
    created_at: datetime = MOMENT,
) -> Job:
    return Job(
        job_id=job_id,
        owner_id="owner-0001",
        job_type=JobType.PREPARE,
        input_hash=DIGEST,
        reference="ref-1",
        status=status,
        generation=generation,
        execution_ref=execution_ref,
        created_at=created_at,
    )


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def engine() -> RecordingWorkflowEngine:
    return RecordingWorkflowEngine()


def seed(store: MemoryStore, *rows: Job) -> None:
    store.transact([Write(key=job_key(j.job_id), item=j, reason="committed") for j in rows])


def row(store: MemoryStore, job_id: str = JOB_ID) -> Job:
    found = read(store, job_key(job_id), Job)
    assert found is not None
    return found


def controller(store: MemoryStore, engine: RecordingWorkflowEngine, **kwargs: int) -> JobController:
    return JobController(store=store, engine=engine, **kwargs)


# -- starting ---------------------------------------------------------------


def test_a_queued_job_starts_under_its_own_run_id(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The name is the domain's ``run_id``, not a format this layer rebuilds."""
    seed(store, job())
    resolved = controller(store, engine).deliver(JOB_ID)
    assert isinstance(resolved, JobResolved)
    assert resolved.run_id == "job-0000001-r1" == job().run_id
    assert resolved.started_new_run is True
    assert row(store).status is JobState.RUNNING
    assert row(store).execution_ref == resolved.execution_ref


def test_a_job_that_does_not_exist_is_reported_not_raised(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    assert controller(store, engine).deliver("job-0000404") == JobNotFound(job_id="job-0000404")


def test_a_duplicate_delivery_produces_exactly_one_run(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The guarantee the whole design turns on.

    The second delivery resolves to the run that exists. It is not an error, and
    it does not start anything: the collision on the name *is* the suppression.
    """
    seed(store, job())
    control = controller(store, engine)
    first = control.deliver(JOB_ID)
    second = control.deliver(JOB_ID)
    assert isinstance(first, JobResolved) and isinstance(second, JobResolved)
    assert first.run_id == second.run_id
    assert first.started_new_run is True
    assert second.started_new_run is False
    assert engine.runs() == 1


def test_a_delivery_that_arrives_while_running_resolves_to_the_same_run(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    seed(store, job(status=JobState.RUNNING, execution_ref="arn:fake:execution:job-0000001-r1"))
    resolved = controller(store, engine).deliver(JOB_ID)
    assert isinstance(resolved, JobResolved)
    assert resolved.run_id == "job-0000001-r1"
    assert resolved.started_new_run is False
    assert engine.started == [], "a running job must not be handed to the engine again"


def test_a_delivery_for_a_failed_job_resolves_and_never_revives_it(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """Only an authorised retry revives a failed job, and only by generation."""
    seed(store, job(status=JobState.FAILED, execution_ref="arn:fake:execution:job-0000001-r1"))
    resolved = controller(store, engine).deliver(JOB_ID)
    assert isinstance(resolved, JobResolved)
    assert resolved.started_new_run is False
    assert row(store).status is JobState.FAILED
    assert row(store).generation == 1
    assert engine.started == []


def test_a_delivery_for_a_succeeded_job_does_not_run_it_again(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    seed(store, job(status=JobState.SUCCEEDED, execution_ref="arn:fake:execution:job-0000001-r1"))
    resolved = controller(store, engine).deliver(JOB_ID)
    assert isinstance(resolved, JobResolved)
    assert resolved.started_new_run is False
    assert engine.started == []


def test_the_payload_does_not_change_once_the_job_is_running() -> None:
    """Step Functions compares inputs, so the payload has to be stable.

    A payload that carried ``status`` or ``execution_ref`` would differ the
    moment the first start succeeded, and every ordinary duplicate would take
    the ``ExecutionAlreadyExists`` path instead of the quiet one.
    """
    queued = job()
    running = job(status=JobState.RUNNING, execution_ref="arn:fake:execution:job-0000001-r1")
    assert execution_payload(queued) == execution_payload(running)


def test_the_payload_changes_when_the_generation_does() -> None:
    assert execution_payload(job(generation=1)) != execution_payload(job(generation=2))


# -- retry versus replay ----------------------------------------------------


def test_a_retry_increments_the_generation_and_is_a_new_run(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    seed(store, job(status=JobState.FAILED, execution_ref="arn:fake:execution:job-0000001-r1"))
    resolved = controller(store, engine).retry(JOB_ID)
    assert isinstance(resolved, JobResolved)
    assert resolved.run_id == "job-0000001-r2"
    assert resolved.started_new_run is True
    assert row(store).generation == 2
    assert row(store).status is JobState.RUNNING


def test_a_replay_never_increments_the_generation(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The bug this distinction exists to catch.

    A replay re-delivers an existing event. If it ever produced a new
    generation it would produce a new execution name, and the duplicate
    suppression that the name provides would be bypassed entirely.
    """
    seed(store, job())
    control = controller(store, engine)
    control.deliver(JOB_ID)
    for _ in range(3):
        control.deliver(JOB_ID)
    assert row(store).generation == 1
    assert engine.runs() == 1


def test_a_retry_and_a_replay_differ_only_in_the_generation(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """Both directions in one place, because the pair is the rule."""
    seed(store, job())
    control = controller(store, engine)
    control.deliver(JOB_ID)
    engine.finish("job-0000001-r1", ExecutionState.FAILED, error_code="task_failed")
    control.repair(JOB_ID)

    control.deliver(JOB_ID)  # a replay of the original delivery
    assert row(store).generation == 1
    assert engine.runs() == 1

    control.retry(JOB_ID)  # an authorised retry
    assert row(store).generation == 2
    assert engine.runs() == 2


def test_retrying_a_running_job_is_refused_by_the_domain(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The transition table says so; the controller does not get a second opinion."""
    seed(store, job(status=JobState.RUNNING, execution_ref="arn:fake:execution:job-0000001-r1"))
    assert isinstance(controller(store, engine).retry(JOB_ID), IllegalTransition)
    assert row(store).generation == 1


def test_retrying_a_job_that_does_not_exist_is_reported_not_raised(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    assert controller(store, engine).retry("job-0000404") == JobNotFound(job_id="job-0000404")


# -- the retry cap ----------------------------------------------------------


def test_retries_stop_at_the_cap(store: MemoryStore, engine: RecordingWorkflowEngine) -> None:
    seed(store, job(status=JobState.FAILED, generation=DEFAULT_MAX_GENERATIONS))
    refused = controller(store, engine).retry(JOB_ID)
    assert isinstance(refused, RetryCapReached)
    assert engine.started == []
    assert row(store).generation == DEFAULT_MAX_GENERATIONS


def test_the_refusal_carries_the_cap_so_it_need_not_be_inferred(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """A generation with nothing to compare it to does not explain anything."""
    seed(store, job(status=JobState.FAILED, generation=2))
    refused = controller(store, engine, max_generations=2).retry(JOB_ID)
    assert refused == RetryCapReached(job_id=JOB_ID, generation=2, cap=2)


def test_the_cap_admits_the_generation_below_it(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    seed(store, job(status=JobState.FAILED, generation=2))
    resolved = controller(store, engine, max_generations=3).retry(JOB_ID)
    assert isinstance(resolved, JobResolved)
    assert row(store).generation == 3


def test_the_cap_is_a_cap_and_not_a_transition_rule(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """Refusing to ask is not the same as deciding the transition.

    The job is untouched: no status change, no error code overwritten, nothing
    that would destroy the reason it failed in the first place.
    """
    failed = job(status=JobState.FAILED, generation=DEFAULT_MAX_GENERATIONS)
    seed(store, failed)
    controller(store, engine).retry(JOB_ID)
    assert row(store) == failed


# -- repair -----------------------------------------------------------------


def running_job(store: MemoryStore, engine: RecordingWorkflowEngine) -> JobController:
    seed(store, job())
    control = controller(store, engine)
    control.deliver(JOB_ID)
    return control


def test_we_stopped_watching_is_not_it_failed(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The rule this whole repair path exists to hold.

    However long the job has been quiet, the engine says the run is alive. A
    watcher that marked it failed would be inventing a job failure -- and a job
    failure is the one thing that must never be mistaken for a payment outcome.
    """
    control = running_job(store, engine)
    repaired = control.repair(JOB_ID)
    assert repaired == Repaired(JOB_ID, RepairAction.STILL_RUNNING, JobState.RUNNING)
    assert row(store).status is JobState.RUNNING
    assert row(store).error_code is None


def test_an_execution_the_engine_cannot_find_leaves_the_job_running(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """Absence of information is not information.

    "The engine has never heard of this" and "the engine says it failed" lead to
    opposite actions, so they must not collapse into one answer.
    """
    control = running_job(store, engine)
    engine.forget("job-0000001-r1")
    repaired = control.repair(JOB_ID)
    assert repaired == Repaired(JOB_ID, RepairAction.UNKNOWN_TO_THE_ENGINE, JobState.RUNNING)
    assert row(store).status is JobState.RUNNING


def test_a_job_running_with_no_execution_recorded_is_left_alone(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The crash landed between starting the run and writing the row down."""
    seed(store, job(status=JobState.RUNNING))
    repaired = controller(store, engine).repair(JOB_ID)
    assert repaired == Repaired(JOB_ID, RepairAction.NEVER_STARTED, JobState.RUNNING)
    assert row(store).status is JobState.RUNNING


def test_a_timed_out_execution_settles_the_job_as_failed(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """A timeout the *engine* reports is a finding. A silence is not."""
    control = running_job(store, engine)
    engine.finish("job-0000001-r1", ExecutionState.TIMED_OUT)
    repaired = control.repair(JOB_ID)
    assert repaired == Repaired(JOB_ID, RepairAction.FAILED, JobState.FAILED)
    assert row(store).error_code == TIMED_OUT_CODE


def test_a_succeeded_execution_settles_the_job(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    control = running_job(store, engine)
    engine.finish("job-0000001-r1", ExecutionState.SUCCEEDED, result_ref="pp-000001")
    repaired = control.repair(JOB_ID)
    assert repaired == Repaired(JOB_ID, RepairAction.SUCCEEDED, JobState.SUCCEEDED)
    assert row(store).result_ref == "pp-000001"
    assert row(store).progress == 100


def test_a_failed_execution_keeps_the_engines_own_error_code(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    control = running_job(store, engine)
    engine.finish("job-0000001-r1", ExecutionState.FAILED, error_code="States.TaskFailed")
    control.repair(JOB_ID)
    assert row(store).error_code == "States.TaskFailed"


def test_an_aborted_execution_is_not_reported_as_an_ordinary_failure(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """Someone stopped it, which is a different thing for an operator to read."""
    control = running_job(store, engine)
    engine.finish("job-0000001-r1", ExecutionState.ABORTED)
    control.repair(JOB_ID)
    assert row(store).error_code == "execution_aborted"


def test_repairing_a_job_that_is_not_running_does_nothing(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    seed(store, job(status=JobState.SUCCEEDED))
    repaired = controller(store, engine).repair(JOB_ID)
    assert repaired == Repaired(JOB_ID, RepairAction.NOT_RUNNING, JobState.SUCCEEDED)


def test_repair_is_idempotent(store: MemoryStore, engine: RecordingWorkflowEngine) -> None:
    """Repair runs on a schedule, so running twice must not be different."""
    control = running_job(store, engine)
    engine.finish("job-0000001-r1", ExecutionState.SUCCEEDED, result_ref="pp-000001")
    assert control.repair(JOB_ID) == Repaired(JOB_ID, RepairAction.SUCCEEDED, JobState.SUCCEEDED)
    assert control.repair(JOB_ID) == Repaired(JOB_ID, RepairAction.NOT_RUNNING, JobState.SUCCEEDED)


def test_repairing_a_job_that_does_not_exist_is_reported_not_raised(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    assert controller(store, engine).repair("job-0000404") == JobNotFound(job_id="job-0000404")


# -- finding the ones worth looking at --------------------------------------


def test_a_job_running_longer_than_the_window_is_worth_asking_about(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    control = running_job(store, engine)
    assert control.stale_running(MOMENT + timedelta(seconds=901)) == [JOB_ID]


def test_a_job_inside_the_window_is_not_listed(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    control = running_job(store, engine)
    assert control.stale_running(MOMENT + timedelta(seconds=60)) == []


def test_only_running_jobs_are_listed(store: MemoryStore, engine: RecordingWorkflowEngine) -> None:
    """A finished job is not stale however old it is."""
    seed(
        store,
        job(job_id="job-0000002", status=JobState.SUCCEEDED),
        job(job_id="job-0000003", status=JobState.QUEUED),
        job(job_id="job-0000004", status=JobState.FAILED),
    )
    control = running_job(store, engine)
    assert control.stale_running(MOMENT + timedelta(days=1)) == [JOB_ID]


def test_being_listed_is_a_reason_to_look_not_a_verdict(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The list is the input to repair, and repair is what decides -- so a job
    can be stale for a week and still be left running.
    """
    control = running_job(store, engine)
    assert control.stale_running(MOMENT + timedelta(days=7)) == [JOB_ID]
    assert control.repair(JOB_ID).action is RepairAction.STILL_RUNNING  # type: ignore[union-attr]
    assert row(store).status is JobState.RUNNING


# -- staleness is about the run, not the job (M2) ---------------------------


def timed(store: MemoryStore, clock: FixedClock) -> tuple[JobController, RecordingWorkflowEngine]:
    """A controller whose engine records when each run began."""
    engine = RecordingWorkflowEngine(clock=clock)
    return JobController(store=store, engine=engine), engine


def test_a_job_retried_a_moment_ago_is_not_stale(store: MemoryStore) -> None:
    """The bug this replaces.

    ``retry()`` starts a new execution and leaves ``created_at`` alone, so
    measuring from the job reported a run that began one second ago as long
    overdue -- and the stale list would fill with exactly the jobs somebody had
    just intervened on.
    """
    clock = FixedClock(MOMENT)
    control, engine = timed(store, clock)
    seed(store, job())
    control.deliver(JOB_ID)

    clock.advance(2000)
    assert control.stale_running(clock.now()) == [JOB_ID], "the first run is overdue"

    engine.finish("job-0000001-r1", ExecutionState.FAILED, error_code="task_failed")
    control.repair(JOB_ID)
    control.retry(JOB_ID)

    clock.advance(1)
    assert control.stale_running(clock.now()) == [], "the new run has barely started"
    assert row(store).generation == 2
    assert row(store).created_at == MOMENT, "the job is old; the run is not"


def test_a_long_running_execution_is_still_reported(store: MemoryStore) -> None:
    clock = FixedClock(MOMENT)
    control, _ = timed(store, clock)
    seed(store, job())
    control.deliver(JOB_ID)
    clock.advance(901)
    assert control.stale_running(clock.now()) == [JOB_ID]


def test_a_job_running_with_no_execution_falls_back_to_its_creation(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """Running with nothing to ask about is worth surfacing, not hiding behind
    a missing timestamp.
    """
    seed(store, job(status=JobState.RUNNING))
    assert controller(store, engine).stale_running(MOMENT + timedelta(days=1)) == [JOB_ID]


def test_an_engine_that_reports_no_start_time_falls_back_to_creation(
    store: MemoryStore, engine: RecordingWorkflowEngine
) -> None:
    """The default fake records no start time, so this is the fallback path."""
    control = controller(store, engine)
    seed(store, job())
    control.deliver(JOB_ID)
    assert control.stale_running(MOMENT + timedelta(days=1)) == [JOB_ID]
    assert control.stale_running(MOMENT + timedelta(seconds=1)) == []
