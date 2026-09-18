"""Jobs, generations and duplicate delivery (WP-02 criterion 12 support).

The rule with teeth: an authorised retry increments the generation; duplicate
delivery never does, and never revives a failed run.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services.domain.errors import IllegalTransition
from services.domain.jobs import (
    Job,
    JobType,
    fail,
    resolve_delivery,
    retry,
    start,
    succeed,
)
from services.domain.transitions import JobState

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def a_job(status: JobState = JobState.QUEUED, generation: int = 1) -> Job:
    return Job(
        job_id="job-00000001",
        owner_id="owner-0001",
        job_type=JobType.CHECKOUT,
        input_hash="a" * 64,
        reference="purchase-001",
        status=status,
        generation=generation,
        created_at=NOW,
    )


def test_the_run_id_is_generation_specific() -> None:
    assert a_job().run_id == "job-00000001-r1"
    assert a_job(generation=4).run_id == "job-00000001-r4"


def test_duplicate_delivery_resolves_the_same_run_and_starts_nothing() -> None:
    job = a_job(status=JobState.RUNNING)
    result = resolve_delivery(job)
    assert result.run_id == job.run_id
    assert result.started_new_run is False


def test_duplicate_delivery_of_a_failed_job_does_not_revive_it() -> None:
    """Only an authorised retry does that, and only by bumping the generation."""
    job = a_job(status=JobState.FAILED)
    result = resolve_delivery(job)
    assert result.started_new_run is False
    assert result.run_id == "job-00000001-r1"
    assert job.status is JobState.FAILED


def ok(result: Job | IllegalTransition) -> Job:
    """Narrow a transition that this test expects to be legal.

    The transitions return a union so an illegal move is a value, not an
    exception. Asserting once here keeps that discipline while letting the
    chained calls below read as the sequence they describe.
    """
    assert isinstance(result, Job), f"expected a legal transition, got {result}"
    return result


def test_a_retry_increments_the_generation_and_requeues() -> None:
    failed = fail(ok(start(a_job(), "arn:execution:1")), "provider_unreachable")
    assert isinstance(failed, Job)
    assert failed.status is JobState.FAILED

    retried = retry(failed)
    assert isinstance(retried, Job)
    assert retried.status is JobState.QUEUED
    assert retried.generation == 2
    assert retried.run_id == "job-00000001-r2"
    assert retried.error_code is None


def test_a_retry_preserves_every_business_identity() -> None:
    """The generation changes; nothing that a provider key derives from does."""
    failed = fail(ok(start(a_job(), "arn:execution:1")), "timeout")
    assert isinstance(failed, Job)
    retried = retry(failed)
    assert isinstance(retried, Job)
    assert retried.job_id == failed.job_id
    assert retried.reference == failed.reference
    assert retried.input_hash == failed.input_hash
    assert retried.owner_id == failed.owner_id


def test_a_succeeded_job_cannot_be_retried() -> None:
    done = succeed(ok(start(a_job(), "arn:execution:1")))
    assert isinstance(done, Job)
    assert isinstance(retry(done), IllegalTransition)


def test_a_queued_job_cannot_be_retried() -> None:
    assert isinstance(retry(a_job()), IllegalTransition)


def test_a_job_cannot_succeed_without_running() -> None:
    assert isinstance(succeed(a_job()), IllegalTransition)


def test_progress_reaches_one_hundred_on_success() -> None:
    done = succeed(ok(start(a_job(), "arn:execution:1")), result_ref="result-01")
    assert isinstance(done, Job)
    assert done.progress == 100
    assert done.result_ref == "result-01"


def test_a_job_failure_carries_a_code_and_nothing_about_payment() -> None:
    """A failed job says nothing about money, so it holds no payment field."""
    failed = fail(ok(start(a_job(), "arn:execution:1")), "agent_timeout")
    assert isinstance(failed, Job)
    assert failed.error_code == "agent_timeout"
    assert "payment" not in Job.model_fields
    assert "provider" not in Job.model_fields
