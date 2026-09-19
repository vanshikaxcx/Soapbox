"""What an operator can do, and what it leaves behind (WP-07).

Two properties carry the weight. A retry goes through the controller, so the cap
applies to a human exactly as it applies to a redelivery -- an operator script
that reached past it would turn a bounded retry into an unbounded one with
someone's name on it. And a replay re-delivers without re-deciding: the
generation does not move, so the execution name does not move, so the run that
exists is the run it resolves to.

The rest is about the record. Every action leaves one, refusals included,
because "the operator tried and was told no" is the entry most worth having.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.application.controller import DEFAULT_MAX_GENERATIONS, JobController
from services.application.fakes import (
    FixedClock,
    MemoryStore,
    RecordingEventBus,
    RecordingWorkflowEngine,
    SequentialIds,
)
from services.application.operations import (
    AUDIT_PREFIX,
    AuditRecord,
    OperatorAction,
    OperatorConsole,
    Outcome,
    audit_key,
)
from services.application.outbox import outbox_key
from services.application.ports import Write, read
from services.application.purchase import job_key
from services.domain.jobs import Job, JobType, OutboxEvent, PublicationState
from services.domain.transitions import JobState

NOW = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
OPERATOR = "operator-0001"
JOB_ID = "job-0000001"
EVENT_ID = "event-00000001"


def job(*, status: JobState = JobState.FAILED, generation: int = 1) -> Job:
    return Job(
        job_id=JOB_ID,
        owner_id="owner-0001",
        job_type=JobType.CHECKOUT,
        input_hash="a" * 64,
        reference="attempt-0001",
        status=status,
        generation=generation,
        execution_ref="arn:fake:execution:job-0000001-r1",
        created_at=NOW,
    )


def event(*, state: PublicationState = PublicationState.PUBLISHED) -> OutboxEvent:
    """An event in the state a replay actually finds one in.

    ``published`` by default, deliberately. A replay exists for the case where
    the publisher already sent it and it did not take effect, so seeding a
    ``pending`` row would test the one situation a replay is never for -- and
    would make "the state is not wound back" pass without meaning anything,
    because there would be nothing to wind back from.
    """
    return OutboxEvent(
        event_id=EVENT_ID,
        event_type="purchase.checkout_requested",
        aggregate_id="pp-000001",
        aggregate_version=2,
        owner_id="owner-0001",
        occurred_at=NOW,
        reference=JOB_ID,
        publication_state=state,
    )


class Desk:
    """An operator's console, with the world it acts on."""

    def __init__(self, *, max_generations: int = DEFAULT_MAX_GENERATIONS) -> None:
        self.store = MemoryStore()
        self.engine = RecordingWorkflowEngine()
        self.bus = RecordingEventBus()
        self.controller = JobController(
            store=self.store, engine=self.engine, max_generations=max_generations
        )
        self.console = OperatorConsole(
            store=self.store,
            controller=self.controller,
            bus=self.bus,
            clock=FixedClock(NOW),
            ids=SequentialIds(),
        )

    def given(self, *items: Job | OutboxEvent) -> None:
        writes = []
        for item in items:
            key = job_key(item.job_id) if isinstance(item, Job) else outbox_key(item.event_id)
            writes.append(Write(key=key, item=item, reason="committed"))
        self.store.transact(writes)

    def job_row(self) -> Job:
        found = read(self.store, job_key(JOB_ID), Job)
        assert found is not None
        return found


@pytest.fixture
def desk() -> Desk:
    return Desk()


# -- retry ------------------------------------------------------------------


def test_a_retry_runs_the_job_again_under_a_new_generation(desk: Desk) -> None:
    desk.given(job())
    record = desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    assert record.action is OperatorAction.RETRY_JOB
    assert record.outcome is Outcome.DONE
    assert record.detail == "job-0000001-r2"
    assert desk.job_row().generation == 2
    assert desk.engine.runs() == 1


def test_the_cap_applies_to_an_operator_exactly_as_it_applies_to_anything_else(
    desk: Desk,
) -> None:
    """The reason a retry goes through the controller rather than around it.

    ``jobs.retry()`` is right there and calling it directly would be shorter. It
    would also turn a bounded retry into an unbounded one with a human's name on
    it, which is precisely what the cap exists to stop.
    """
    desk.given(job(generation=DEFAULT_MAX_GENERATIONS))
    record = desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    assert record.outcome is Outcome.REFUSED_BY_THE_CAP
    assert record.detail == f"generation {DEFAULT_MAX_GENERATIONS} of {DEFAULT_MAX_GENERATIONS}"
    assert desk.job_row().generation == DEFAULT_MAX_GENERATIONS
    assert desk.engine.started == []


def test_a_refusal_is_still_recorded(desk: Desk) -> None:
    """The entry most worth having: the operator tried, and was told no."""
    desk.given(job(generation=DEFAULT_MAX_GENERATIONS))
    desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    assert len(desk.console.history()) == 1


def test_retrying_a_running_job_records_what_the_rule_said(desk: Desk) -> None:
    desk.given(job(status=JobState.RUNNING))
    record = desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    assert record.outcome is Outcome.REFUSED_BY_THE_RULES
    assert record.detail == "illegal_transition"


def test_retrying_a_job_that_is_not_there_records_that_too(desk: Desk) -> None:
    record = desk.console.retry_job(operator_id=OPERATOR, job_id="job-0000404")
    assert record.outcome is Outcome.REFUSED_BY_THE_RULES
    assert record.detail == "job_not_found"


def test_the_operator_is_named_and_never_inferred(desk: Desk) -> None:
    """An audit trail whose actor is "whoever had the credentials" answers nothing."""
    desk.given(job())
    record = desk.console.retry_job(operator_id="operator-0042", job_id=JOB_ID)
    assert record.operator_id == "operator-0042"


# -- replay -----------------------------------------------------------------


def test_a_replay_puts_the_event_back_on_the_bus(desk: Desk) -> None:
    desk.given(event())
    record = desk.console.replay_event(operator_id=OPERATOR, event_id=EVENT_ID)
    assert record.outcome is Outcome.DONE
    assert [e.event_id for e in desk.bus.published] == [EVENT_ID]


def test_a_replay_never_increments_the_generation(desk: Desk) -> None:
    """The bug this distinction exists to catch, in the tool most able to cause it.

    A replay that incremented the generation would change the execution name,
    and the duplicate suppression the whole design rests on would be bypassed by
    the very thing meant to recover from a duplicate.
    """
    desk.given(job(status=JobState.QUEUED), event())
    desk.console.replay_event(operator_id=OPERATOR, event_id=EVENT_ID)
    desk.console.replay_event(operator_id=OPERATOR, event_id=EVENT_ID)
    assert desk.job_row().generation == 1
    assert desk.job_row().run_id == "job-0000001-r1"


def test_a_replay_does_not_rewrite_the_publication_state(desk: Desk) -> None:
    """The row records that we sent it, and a replay is for when sending was not
    the same as arriving. Winding the state back would make the ordinary
    publisher send it a third time, unasked.
    """
    committed = event(state=PublicationState.PUBLISHED)
    desk.given(committed)
    desk.console.replay_event(operator_id=OPERATOR, event_id=EVENT_ID)
    row = read(desk.store, outbox_key(EVENT_ID), OutboxEvent)
    assert row == committed
    assert row is not None
    assert row.publication_state is PublicationState.PUBLISHED


def test_a_replay_sends_the_event_exactly_as_committed(desk: Desk) -> None:
    committed = event()
    desk.given(committed)
    desk.console.replay_event(operator_id=OPERATOR, event_id=EVENT_ID)
    assert desk.bus.published == [committed]


def test_replaying_an_event_that_is_not_there_is_recorded_not_raised(desk: Desk) -> None:
    record = desk.console.replay_event(operator_id=OPERATOR, event_id="event-00000404")
    assert record.outcome is Outcome.NOTHING_TO_ACT_ON
    assert desk.bus.published == []


def test_a_bus_refusal_is_recorded_with_the_reason() -> None:
    desk = Desk()
    desk.bus.refuse[EVENT_ID] = "ThrottlingException"
    desk.given(event())
    record = desk.console.replay_event(operator_id=OPERATOR, event_id=EVENT_ID)
    assert record.outcome is Outcome.REJECTED_BY_THE_BUS
    assert record.detail == "ThrottlingException"


# -- the record itself ------------------------------------------------------


def test_every_action_leaves_exactly_one_record(desk: Desk) -> None:
    desk.given(job(), event())
    desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    desk.console.replay_event(operator_id=OPERATOR, event_id=EVENT_ID)
    assert len(desk.console.history()) == 2
    assert desk.store.count_matching(AUDIT_PREFIX) == 2


def test_the_record_is_committed_where_it_can_be_found(desk: Desk) -> None:
    desk.given(job())
    record = desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    stored = read(desk.store, audit_key(record.operation_id), AuditRecord)
    assert stored == record


def test_the_audit_trail_lives_outside_the_aggregates_it_describes(desk: Desk) -> None:
    """An operator action is a record *about* the system, not part of its state.

    Filed inside a purchase it would travel with that purchase -- into its
    exports, its evidence and its case file -- and an operator's name does not
    belong in a shopper's receipt.
    """
    desk.given(job())
    desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    assert desk.store.count_matching("PURCHASE#") == 0
    assert desk.store.count_matching("JOB#") == 1
    assert desk.store.count_matching(AUDIT_PREFIX) == 1


def test_two_actions_never_share_a_record(desk: Desk) -> None:
    """The write is conditional, so a repeated operation id would be refused
    rather than quietly overwriting the earlier action's entry.
    """
    desk.given(job())
    first = desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    second = desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    assert first.operation_id != second.operation_id
    assert len(desk.console.history()) == 2


def test_the_record_carries_the_moment_from_the_clock_port(desk: Desk) -> None:
    desk.given(job())
    record = desk.console.retry_job(operator_id=OPERATOR, job_id=JOB_ID)
    assert record.recorded_at == NOW


def test_an_empty_desk_has_no_history(desk: Desk) -> None:
    assert desk.console.history() == []
