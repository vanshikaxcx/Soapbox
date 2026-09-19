"""What the outbox publisher promises (WP-07).

The publisher is the one place where "committed" turns into "published", so
every test here is about a partial failure: which events landed, which are
retried, and what the row says afterwards. A test that only proved the happy
path would not distinguish this publisher from one that republishes everything
on every delivery.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime

import pytest

from services.application.fakes import MemoryStore, RecordingEventBus
from services.application.outbox import OutboxPublisher, PublicationOutcome
from services.application.ports import Write, read
from services.application.purchase import outbox_key
from services.domain.jobs import OutboxEvent, PublicationState

MOMENT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)


def event(event_id: str, *, state: PublicationState = PublicationState.PENDING) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id,
        event_type="purchase.checkout_requested",
        aggregate_id="pp-000001",
        aggregate_version=2,
        owner_id="owner-0001",
        occurred_at=MOMENT,
        reference="ref-1",
        publication_state=state,
    )


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def bus() -> RecordingEventBus:
    return RecordingEventBus()


def seed(store: MemoryStore, *events: OutboxEvent) -> None:
    store.transact(
        [Write(key=outbox_key(e.event_id), item=e, reason="committed by WP-08") for e in events]
    )


def state_of(store: MemoryStore, event_id: str) -> PublicationState:
    row = read(store, outbox_key(event_id), OutboxEvent)
    assert row is not None
    return row.publication_state


def test_a_pending_event_is_published_and_marked(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    seed(store, event("ev-000001"))
    outcome = OutboxPublisher(store=store, bus=bus).publish(["ev-000001"])
    assert outcome == PublicationOutcome(published=("ev-000001",))
    assert [e.event_id for e in bus.published] == ["ev-000001"]
    assert state_of(store, "ev-000001") is PublicationState.PUBLISHED


def test_an_already_published_event_is_skipped_not_republished(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    """Redelivery is normal; republishing on every redelivery is not.

    Skipped rather than failed, because a retry cannot improve it and reporting
    it as a failure would make the source redeliver it forever.
    """
    seed(store, event("ev-000001", state=PublicationState.PUBLISHED))
    outcome = OutboxPublisher(store=store, bus=bus).publish(["ev-000001"])
    assert outcome == PublicationOutcome(skipped=("ev-000001",))
    assert bus.published == []


def test_an_event_whose_row_has_gone_is_not_called_skipped(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    """Missing is not the same as done, and it used to be reported as done.

    An outbox row is committed in the same transaction as the state it
    describes, and a guard asserts that nothing in the tree deletes one. So a
    row that is not there is a committed command that has gone missing -- which
    was being answered with silence, in the same field used for "already sent".
    """
    outcome = OutboxPublisher(store=store, bus=bus).publish(["ev-000009"])
    assert outcome == PublicationOutcome(vanished=("ev-000009",))
    assert outcome.skipped == ()
    assert bus.batches == []


def test_a_vanished_row_and_a_published_row_are_told_apart(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    seed(store, event("ev-000001", state=PublicationState.PUBLISHED))
    outcome = OutboxPublisher(store=store, bus=bus).publish(["ev-000001", "ev-000009"])
    assert outcome.skipped == ("ev-000001",)
    assert outcome.vanished == ("ev-000009",)


def test_the_publisher_reads_the_row_rather_than_trusting_the_delivery(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    """A delivery names an id; the row is what gets published.

    The stream record is a snapshot of a moment and the row is the truth now, so
    a replayed delivery has to resolve to current state rather than resurrect
    what was true when it was first written.
    """
    seed(store, event("ev-000001"))
    seed(store, event("ev-000001", state=PublicationState.PUBLISHED))
    outcome = OutboxPublisher(store=store, bus=bus).publish(["ev-000001"])
    assert outcome.skipped == ("ev-000001",)
    assert bus.published == []


def test_one_rejected_entry_does_not_hold_back_the_others(
    store: MemoryStore,
) -> None:
    """The defect this is all built to avoid.

    EventBridge refuses one entry inside an otherwise successful call. The other
    two must land, be marked, and never be republished; only the refused one is
    reported for retry.
    """
    seed(store, event("ev-000001"), event("ev-000002"), event("ev-000003"))
    bus = RecordingEventBus(refuse={"ev-000002": "ThrottlingException"})
    outcome = OutboxPublisher(store=store, bus=bus).publish(["ev-000001", "ev-000002", "ev-000003"])
    assert outcome.published == ("ev-000001", "ev-000003")
    assert outcome.failed == ("ev-000002",)
    assert state_of(store, "ev-000001") is PublicationState.PUBLISHED
    assert state_of(store, "ev-000003") is PublicationState.PUBLISHED


def test_a_rejected_entry_stays_pending_so_it_is_published_later(
    store: MemoryStore,
) -> None:
    seed(store, event("ev-000002"))
    bus = RecordingEventBus(refuse={"ev-000002": "InternalException"})
    OutboxPublisher(store=store, bus=bus).publish(["ev-000002"])
    assert state_of(store, "ev-000002") is PublicationState.PENDING


def test_a_rejected_entry_is_published_on_the_next_delivery(store: MemoryStore) -> None:
    """Retry has to actually work, not merely be reported."""
    seed(store, event("ev-000002"))
    refusing = RecordingEventBus(refuse={"ev-000002": "ThrottlingException"})
    assert OutboxPublisher(store=store, bus=refusing).publish(["ev-000002"]).failed == (
        "ev-000002",
    )
    accepting = RecordingEventBus()
    assert OutboxPublisher(store=store, bus=accepting).publish(["ev-000002"]).published == (
        "ev-000002",
    )
    assert state_of(store, "ev-000002") is PublicationState.PUBLISHED


def test_the_whole_batch_reaches_the_bus_in_one_call(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    """Batching is the bus adapter's business, not the publisher's."""
    seed(store, event("ev-000001"), event("ev-000002"))
    OutboxPublisher(store=store, bus=bus).publish(["ev-000001", "ev-000002"])
    assert len(bus.batches) == 1
    assert [e.event_id for e in bus.batches[0]] == ["ev-000001", "ev-000002"]


def test_a_repeated_id_in_one_batch_is_published_once(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    """Two stream records can name the same row; that is one event, not two."""
    seed(store, event("ev-000001"))
    outcome = OutboxPublisher(store=store, bus=bus).publish(["ev-000001", "ev-000001"])
    assert outcome.published == ("ev-000001",)
    assert len(bus.published) == 1


def test_nothing_pending_means_the_bus_is_not_called_at_all(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    seed(store, event("ev-000001", state=PublicationState.PUBLISHED))
    OutboxPublisher(store=store, bus=bus).publish(["ev-000001"])
    assert bus.batches == []


def test_an_empty_delivery_publishes_nothing(store: MemoryStore, bus: RecordingEventBus) -> None:
    assert OutboxPublisher(store=store, bus=bus).publish([]) == PublicationOutcome()
    assert bus.batches == []


def test_a_bus_fault_is_not_swallowed(store: MemoryStore) -> None:
    """A total outage is the one case where failing the whole batch is right.

    Nothing was published, so there is nothing to report per entry, and turning
    it into a list of per-item failures would claim knowledge we do not have.
    """

    class BrokenBus:
        def publish(self, events: object) -> list[object]:
            raise ConnectionError("no route to the bus")

    seed(store, event("ev-000001"))
    with pytest.raises(ConnectionError):
        OutboxPublisher(store=store, bus=BrokenBus()).publish(["ev-000001"])  # type: ignore[arg-type]
    assert state_of(store, "ev-000001") is PublicationState.PENDING


def test_the_publisher_writes_nothing_but_the_publication_state(
    store: MemoryStore, bus: RecordingEventBus
) -> None:
    """The publisher catches up; it never decides.

    Every other field is the one WP-08 committed, and the only key it touches is
    the outbox row's own.
    """
    original = event("ev-000001")
    seed(store, original)
    store.transactions.clear()
    OutboxPublisher(store=store, bus=bus).publish(["ev-000001"])

    written = [write for transaction in store.transactions for write in transaction]
    assert [w.key for w in written] == [outbox_key("ev-000001")]
    row = read(store, outbox_key("ev-000001"), OutboxEvent)
    assert row is not None
    assert row.model_dump(exclude={"publication_state"}) == original.model_dump(
        exclude={"publication_state"}
    )


def test_the_publisher_uses_wp08s_own_key(store: MemoryStore, bus: RecordingEventBus) -> None:
    """Pinned because a publisher with its own copy of the prefix is a silent
    break waiting for the day one of the two changes.
    """
    assert outbox_key("ev-000001") == ("OUTBOX#ev-000001", "EVENT")


# -- nothing deletes an outbox row ------------------------------------------


def _writes_in(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Write"
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _targets_the_outbox(call: ast.Call) -> bool:
    key = _keyword(call, "key")
    return (
        isinstance(key, ast.Call) and isinstance(key.func, ast.Name) and key.func.id == "outbox_key"
    )


def _is_a_delete(call: ast.Call) -> bool:
    item = _keyword(call, "item")
    # ``Write.item`` defaults to ``None``, so an omitted item is a delete too --
    # which is exactly the way one would be introduced by accident.
    return item is None or (isinstance(item, ast.Constant) and item.value is None)


MODULES = sorted(
    path
    for path in pathlib.Path("services").rglob("*.py")
    if not path.name.endswith("_test.py") and "__pycache__" not in path.parts
)


def test_there_are_modules_to_scan() -> None:
    assert len(MODULES) >= 20, "this guard would pass vacuously"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_nothing_deletes_an_outbox_row(path: pathlib.Path) -> None:
    """The decision behind the publisher ignoring a ``REMOVE`` stream record.

    A deleted outbox row cannot be published: there is nothing left to read, and
    the only way to "handle" the delete would be to publish from the stream's
    old image -- which would make the publisher decide from a snapshot instead of
    catching up from committed state. That is the one property an outbox has, so
    handling a delete is not an option; guaranteeing there are none is.

    So the guarantee is asserted here rather than defended downstream. The day
    pruning is designed, this test fails and whoever writes it has to decide
    what a publisher should do about a row that is about to vanish -- instead of
    discovering months later that a pruned-before-published event went out never
    and reported nothing.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for call in _writes_in(tree):
        if _targets_the_outbox(call) and _is_a_delete(call):
            raise AssertionError(
                f"{path} deletes an outbox row at line {call.lineno}; the publisher "
                "ignores REMOVE records on the guarantee that nothing does"
            )


def test_the_guard_would_notice_an_outbox_delete() -> None:
    """Proves the scan above is capable of failing, both ways a delete is spelt."""
    explicit = ast.parse("Write(key=outbox_key(e), item=None, reason='prune')\n")
    implicit = ast.parse("Write(key=outbox_key(e), reason='prune')\n")
    for tree in (explicit, implicit):
        calls = _writes_in(tree)
        assert calls, "the guard no longer recognises a Write call"
        assert _targets_the_outbox(calls[0])
        assert _is_a_delete(calls[0])


def test_the_guard_does_not_flag_an_ordinary_outbox_write() -> None:
    tree = ast.parse("Write(key=outbox_key(e), item=event, reason='published')\n")
    call = _writes_in(tree)[0]
    assert _targets_the_outbox(call)
    assert not _is_a_delete(call)
