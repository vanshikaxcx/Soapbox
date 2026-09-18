"""One suite, two stores: ``MemoryStore`` and DynamoDB must be interchangeable.

Every test here runs twice, against the fake and against a real DynamoDB served
in-process by ``moto``. That is the point: 951 tests encode the safety argument
for "one approval, one attempt" against the fake, and they are only evidence
about production if the two stores agree. A test written against one store alone
proves that store, and proves nothing about the swap.

So the tests below are written against the *port* -- ``Condition``, ``Write``,
``ConditionFailed`` -- and never against either implementation. If a test needs
to know which store it is talking to, the behaviour it is checking is not part
of the contract and does not belong here.

``moto`` means no AWS account, no network and no credentials: the client is
built with explicit fake keys so a real profile on the machine cannot be picked
up by accident, and each test gets its own table so nothing leaks between them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from mypy_boto3_dynamodb.client import DynamoDBClient

from services.adapters.dynamo_state_store import (
    PARTITION_ATTRIBUTE,
    SORT_ATTRIBUTE,
    TRANSACTION_LIMIT,
    DynamoStateStore,
    TypeTagRefused,
    decode,
    encode,
)
from services.application.fakes import MemoryStore
from services.application.ports import (
    Condition,
    ConditionFailed,
    Key,
    StateStore,
    Write,
)
from services.domain.ids import Record
from services.domain.jobs import Job, JobType
from services.domain.money import Currency, Money
from services.domain.purchase import Preparation

TABLE = "proofpath-conformance"
REGION = "ap-south-1"

DIGEST = "a" * 64
MOMENT = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)

KEY: Key = ("PURCHASE#pp-000001", "PREPARATION#1")
OTHER: Key = ("PURCHASE#pp-000001", "FACTS#1")
ELSEWHERE: Key = ("PROVIDER#sim#pay-0001", "LOOKUP")


def preparation(*, version: int = 1, changes: int = 0) -> Preparation:
    return Preparation(
        preparation_id="prep-0001",
        purchase_id="pp-000001",
        refreshed_at=MOMENT,
        diff_hash=DIGEST,
        change_count=changes,
        version=version,
    )


def job(*, generation: int = 1) -> Job:
    return Job(
        job_id="job-0000001",
        owner_id="owner-0001",
        job_type=JobType.PREPARE,
        input_hash=DIGEST,
        reference="ref-1",
        generation=generation,
        created_at=MOMENT,
    )


@contextmanager
def dynamo() -> Iterator[tuple[DynamoStateStore, DynamoDBClient]]:
    """A DynamoDB served in-process, with its own table and fake credentials.

    Hands back the client beside the store so a test can make the service
    misbehave without reaching into the adapter's internals.
    """
    with mock_aws():
        client = boto3.client(
            "dynamodb",
            region_name=REGION,
            aws_access_key_id="conformance",
            aws_secret_access_key="conformance",
            aws_session_token="conformance",
        )
        client.create_table(
            TableName=TABLE,
            AttributeDefinitions=[
                {"AttributeName": PARTITION_ATTRIBUTE, "AttributeType": "S"},
                {"AttributeName": SORT_ATTRIBUTE, "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": PARTITION_ATTRIBUTE, "KeyType": "HASH"},
                {"AttributeName": SORT_ATTRIBUTE, "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoStateStore(client=client, table_name=TABLE), client


@pytest.fixture(params=["memory", "dynamodb"])
def store(request: pytest.FixtureRequest) -> Iterator[StateStore]:
    """The same tests, once per implementation of the port."""
    if request.param == "memory":
        yield MemoryStore()
        return
    with dynamo() as (adapter, _):
        yield adapter


def put(
    key: Key,
    item: object,
    *,
    condition: Condition = Condition.NONE,
    expected_version: int | None = None,
    reason: str = "conformance",
) -> Write:
    """A write with the noise the tests do not care about filled in."""
    return Write(
        key=key,
        item=item,
        condition=condition,
        expected_version=expected_version,
        reason=reason,
    )


def test_both_stores_satisfy_the_port(store: StateStore) -> None:
    """Including the two prefix methods D-1 added.

    ``StateStore`` is ``runtime_checkable``, so this is a structural check, not
    a subclass one -- which is the whole reason the port is a Protocol. Before
    D-1 an adapter could pass this and still lack ``keys_matching``, because the
    port did not ask for it and ``operator.py`` silenced the type checker.
    """
    assert isinstance(store, StateStore)
    assert callable(store.keys_matching)
    assert callable(store.count_matching)


# -- reads ------------------------------------------------------------------


def test_a_missing_key_reads_as_none(store: StateStore) -> None:
    assert store.get(KEY) is None


def test_a_written_record_reads_back_equal(store: StateStore) -> None:
    assert store.transact([put(KEY, preparation())]) is None
    assert store.get(KEY) == preparation()


def test_integers_survive_the_round_trip_as_integers(store: StateStore) -> None:
    """DynamoDB answers in ``Decimal``; money that came back as a float would be
    a defect, and one that only shows up on an amount that cannot be represented.
    """
    stored = job(generation=7)
    assert store.transact([put(("JOB#job-0000001", "JOB"), stored)]) is None
    found = store.get(("JOB#job-0000001", "JOB"))
    assert isinstance(found, Job)
    assert found.generation == 7
    assert type(found.generation) is int
    assert type(found.progress) is int
    assert found.created_at == MOMENT
    assert found.created_at.tzinfo is not None


def test_money_round_trips_without_becoming_a_float() -> None:
    """Checked on the codec directly, so the claim is about the encoding itself
    and not about whichever record happened to be stored.
    """
    amount = Money(amount_paise=199_999, currency=Currency.INR)
    restored = decode(encode(amount))
    assert restored == amount
    assert isinstance(restored, Money)
    assert type(restored.amount_paise) is int


# -- Condition.NONE ---------------------------------------------------------


def test_condition_none_overwrites_whatever_is_there(store: StateStore) -> None:
    assert store.transact([put(KEY, preparation())]) is None
    assert store.transact([put(KEY, preparation(changes=3))]) is None
    found = store.get(KEY)
    assert isinstance(found, Preparation)
    assert found.change_count == 3


# -- Condition.MUST_NOT_EXIST -----------------------------------------------


def test_must_not_exist_admits_the_first_writer(store: StateStore) -> None:
    write = put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST)
    assert store.transact([write]) is None


def test_must_not_exist_refuses_the_second_writer(store: StateStore) -> None:
    """THE uniqueness guarantee, in miniature: this is the condition that makes
    a duplicate payment key impossible.
    """
    assert store.transact([put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST)]) is None
    second = store.transact([put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST)])
    assert isinstance(second, ConditionFailed)
    assert second.key == KEY
    assert second.reason == "conformance"


# -- Condition.VERSION_MUST_BE ----------------------------------------------


def test_version_must_be_admits_the_matching_version(store: StateStore) -> None:
    assert store.transact([put(KEY, preparation(version=1))]) is None
    advanced = put(
        KEY, preparation(version=2), condition=Condition.VERSION_MUST_BE, expected_version=1
    )
    assert store.transact([advanced]) is None
    found = store.get(KEY)
    assert isinstance(found, Preparation)
    assert found.version == 2


def test_version_must_be_refuses_a_stale_version(store: StateStore) -> None:
    """The lost approve/cancel race. Both callers read version 1; one commits."""
    assert store.transact([put(KEY, preparation(version=1))]) is None
    assert (
        store.transact(
            [
                put(
                    KEY,
                    preparation(version=2),
                    condition=Condition.VERSION_MUST_BE,
                    expected_version=1,
                )
            ]
        )
        is None
    )
    loser = store.transact(
        [
            put(
                KEY,
                preparation(version=2, changes=9),
                condition=Condition.VERSION_MUST_BE,
                expected_version=1,
            )
        ]
    )
    assert isinstance(loser, ConditionFailed)
    assert loser.key == KEY
    found = store.get(KEY)
    assert isinstance(found, Preparation)
    assert found.change_count == 0, "the loser must not have overwritten the winner"


def test_version_must_be_refuses_a_record_that_is_not_there(store: StateStore) -> None:
    """Absent is not version-matching. A store that treated a missing record as
    "no conflict" would let a cancelled purchase be resurrected by a retry.
    """
    failed = store.transact(
        [put(KEY, preparation(), condition=Condition.VERSION_MUST_BE, expected_version=1)]
    )
    assert isinstance(failed, ConditionFailed)
    assert failed.key == KEY


# -- item=None deletes ------------------------------------------------------


def test_item_none_deletes(store: StateStore) -> None:
    """Releasing the basket claim is a delete, and it has to actually remove."""
    assert store.transact([put(KEY, preparation())]) is None
    assert store.transact([put(KEY, None)]) is None
    assert store.get(KEY) is None


def test_deleting_something_absent_is_not_an_error(store: StateStore) -> None:
    assert store.transact([put(KEY, None)]) is None
    assert store.get(KEY) is None


def test_a_delete_commits_with_the_writes_beside_it(store: StateStore) -> None:
    assert store.transact([put(KEY, preparation())]) is None
    assert store.transact([put(KEY, None), put(OTHER, preparation())]) is None
    assert store.get(KEY) is None
    assert store.get(OTHER) == preparation()


def test_a_delete_is_rolled_back_with_everything_else(store: StateStore) -> None:
    """The delete participates in the same all-or-none guarantee as a put.

    A store that applied the delete and then failed on the guarded write would
    have released a claim for a transaction that never happened.
    """
    assert store.transact([put(KEY, preparation()), put(ELSEWHERE, preparation())]) is None
    failed = store.transact(
        [
            put(KEY, None),
            put(ELSEWHERE, preparation(), condition=Condition.MUST_NOT_EXIST),
        ]
    )
    assert isinstance(failed, ConditionFailed)
    assert failed.key == ELSEWHERE
    assert store.get(KEY) == preparation(), "the delete must not have landed"


# -- all-or-none ------------------------------------------------------------


def test_a_failed_condition_anywhere_leaves_nothing_written(store: StateStore) -> None:
    """Partial application is not a degraded outcome; it is corruption.

    The failing write is last here on purpose: an implementation that applied as
    it went would already have committed the two before it.
    """
    assert store.transact([put(ELSEWHERE, preparation())]) is None
    failed = store.transact(
        [
            put(KEY, preparation()),
            put(OTHER, preparation()),
            put(ELSEWHERE, preparation(changes=4), condition=Condition.MUST_NOT_EXIST),
        ]
    )
    assert isinstance(failed, ConditionFailed)
    assert failed.key == ELSEWHERE
    assert store.get(KEY) is None
    assert store.get(OTHER) is None
    found = store.get(ELSEWHERE)
    assert isinstance(found, Preparation)
    assert found.change_count == 0


def test_a_condition_failing_first_also_leaves_nothing_written(store: StateStore) -> None:
    assert store.transact([put(KEY, preparation())]) is None
    failed = store.transact(
        [
            put(KEY, preparation(changes=4), condition=Condition.MUST_NOT_EXIST),
            put(OTHER, preparation()),
        ]
    )
    assert isinstance(failed, ConditionFailed)
    assert store.get(OTHER) is None


def test_every_write_of_a_satisfied_transaction_lands(store: StateStore) -> None:
    """The approval transaction's shape: many guarded writes, one commit."""
    writes = [
        put(
            ("PURCHASE#pp-1", f"ATTEMPT#{index}"), preparation(), condition=Condition.MUST_NOT_EXIST
        )
        for index in range(8)
    ]
    assert store.transact(writes) is None
    assert all(store.get(write.key) is not None for write in writes)


def test_an_empty_transaction_commits_nothing_and_fails_nothing(store: StateStore) -> None:
    """DynamoDB rejects a zero-item transaction outright, so the adapter has to
    answer for the empty case itself rather than let a caller's empty list
    become a service error.
    """
    assert store.transact([]) is None


# -- ConditionFailed is a value ---------------------------------------------


def test_a_lost_race_is_returned_and_never_raised(store: StateStore) -> None:
    """The property the whole application layer depends on.

    No caller of ``transact`` has an ``except``. If a rejected guard arrived as
    an exception it would not be handled anywhere -- it would unwind out of a
    use case that had already decided it was committing.
    """
    assert store.transact([put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST)]) is None
    try:
        outcome = store.transact([put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST)])
    except Exception as exc:  # pragma: no cover - the failure this test exists for
        pytest.fail(f"a rejected guard must be a value, not {type(exc).__name__}")
    assert isinstance(outcome, ConditionFailed)


def test_condition_failed_names_the_write_that_lost(store: StateStore) -> None:
    """A caller distinguishes "approved first" from "cancelled first" by the
    reason, so the wrong write's reason is a wrong 409.
    """
    assert store.transact([put(ELSEWHERE, preparation())]) is None
    failed = store.transact(
        [
            Write(key=KEY, item=preparation(), reason="fine"),
            Write(
                key=ELSEWHERE,
                item=preparation(),
                condition=Condition.MUST_NOT_EXIST,
                reason="THE uniqueness guarantee: no duplicate payment key",
            ),
        ]
    )
    assert isinstance(failed, ConditionFailed)
    assert failed.key == ELSEWHERE
    assert failed.reason == "THE uniqueness guarantee: no duplicate payment key"


# -- prefix reads (D-1) -----------------------------------------------------


def test_keys_matching_returns_the_matching_partitions_sorted(store: StateStore) -> None:
    written = [
        ("PURCHASE#a", "PURCHASE"),
        ("PURCHASE#b", "ATTEMPT#1"),
        ("PURCHASE#a", "ATTEMPT#1"),
        ("PROVIDER#sim#k", "LOOKUP"),
    ]
    assert store.transact([put(key, preparation()) for key in written]) is None
    assert store.keys_matching("PURCHASE#") == [
        ("PURCHASE#a", "ATTEMPT#1"),
        ("PURCHASE#a", "PURCHASE"),
        ("PURCHASE#b", "ATTEMPT#1"),
    ]


def test_keys_matching_matches_the_partition_and_not_the_sort_key(store: StateStore) -> None:
    assert store.transact([put(("PURCHASE#a", "ATTEMPT#1"), preparation())]) is None
    assert store.keys_matching("ATTEMPT#") == []


def test_keys_matching_of_a_whole_partition_does_not_miss_a_longer_one(
    store: StateStore,
) -> None:
    """``PURCHASE#1`` is both a whole partition and a prefix of ``PURCHASE#12``.

    A ``Query`` fast path keyed on "the prefix looks like a partition" would
    return one row here and silently drop the other, so the adapter does not
    take one. This test is the reason.
    """
    assert (
        store.transact(
            [
                put(("PURCHASE#1", "PURCHASE"), preparation()),
                put(("PURCHASE#12", "PURCHASE"), preparation()),
            ]
        )
        is None
    )
    assert store.keys_matching("PURCHASE#1") == [
        ("PURCHASE#1", "PURCHASE"),
        ("PURCHASE#12", "PURCHASE"),
    ]


def test_an_unmatched_prefix_is_empty_rather_than_everything(store: StateStore) -> None:
    assert store.transact([put(KEY, preparation())]) is None
    assert store.keys_matching("NOTHING#") == []
    assert store.count_matching("NOTHING#") == 0


def test_count_matching_agrees_with_keys_matching(store: StateStore) -> None:
    keys = [("PROVIDER#sim#1", "LOOKUP"), ("PROVIDER#sim#2", "LOOKUP"), KEY]
    assert store.transact([put(key, preparation()) for key in keys]) is None
    assert store.count_matching("PROVIDER#") == 2
    assert store.count_matching("PROVIDER#") == len(store.keys_matching("PROVIDER#"))


def test_a_deleted_key_stops_being_counted(store: StateStore) -> None:
    assert store.transact([put(KEY, preparation()), put(OTHER, preparation())]) is None
    assert store.count_matching("PURCHASE#") == 2
    assert store.transact([put(KEY, None)]) is None
    assert store.count_matching("PURCHASE#") == 1
    assert store.keys_matching("PURCHASE#") == [OTHER]


# -- malformed transactions -------------------------------------------------


def test_naming_one_key_twice_is_refused_by_both_stores(store: StateStore) -> None:
    """DynamoDB rejects it outright, so the fake must too.

    It raises rather than returning ``ConditionFailed``: a malformed transaction
    is a bug in the caller, not a lost race, and there is nothing to retry.
    """
    with pytest.raises(ValueError, match="twice"):
        store.transact([put(KEY, preparation()), put(KEY, preparation(changes=2))])
    assert store.get(KEY) is None


# -- the codec --------------------------------------------------------------


class _Loose(Record):
    """A record that is not reachable from ``services.*`` under its own name."""

    value: int


def test_a_type_tag_outside_this_codebase_is_refused() -> None:
    """A type tag is data read back out of the table. Importing whatever it
    names would make the store an execution vector; refusing is the only safe
    reading of an item we did not write.
    """
    with pytest.raises(TypeTagRefused):
        decode({"type": {"S": "os:system"}, "body": {"S": "{}"}})


def test_a_type_tag_naming_nothing_is_refused() -> None:
    with pytest.raises(TypeTagRefused):
        decode({"type": {"S": "services.domain.jobs:NoSuchRecord"}, "body": {"S": "{}"}})


def test_a_record_the_store_cannot_describe_is_refused_on_the_way_in() -> None:
    """Better to refuse at the write than to store something nothing can parse."""
    with pytest.raises(TypeError, match="records"):
        encode(object())


def test_a_locally_defined_record_round_trips_by_its_own_module() -> None:
    """The tag is module plus qualname, so a record defined here resolves here."""
    assert decode(encode(_Loose(value=3))) == _Loose(value=3)


# -- how the adapter reads a cancellation -----------------------------------
#
# Adapter-only, because there is no fake equivalent: ``MemoryStore`` cannot be
# handed a malformed service response. They exist because the conformance suite
# above can only prove the mapping for the cancellations ``moto`` produces, and
# the property has to hold for the ones it does not.


def cancellation(reasons: list[dict[str, str]] | None, *, code: str) -> ClientError:
    response: dict[str, Any] = {"Error": {"Code": code, "Message": "cancelled"}}
    if reasons is not None:
        response["CancellationReasons"] = reasons
    # botocore's stub describes a well-formed response, and the point of these
    # tests is the responses that are not. Narrowed to this one line rather than
    # loosening the adapter, which is where it would actually cost something.
    return ClientError(response, "TransactWriteItems")  # type: ignore[arg-type]


def test_a_cancellation_with_no_reasons_still_returns_rather_than_raises() -> None:
    """A service that cancels without saying why must not become an exception.

    Property 1 does not get to depend on ``CancellationReasons`` arriving: the
    adapter works out which guard would have rejected and returns that, because
    a caller with no ``except`` is equally unprepared either way.
    """
    with dynamo() as (store, client):
        assert store.transact([put(KEY, preparation())]) is None
        writes = [put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST)]
        with patch.object(
            client,
            "transact_write_items",
            side_effect=cancellation(None, code="TransactionCanceledException"),
        ):
            outcome = store.transact(writes)
    assert isinstance(outcome, ConditionFailed)
    assert outcome.key == KEY


def test_a_bare_conditional_check_failure_is_returned_rather_than_raised() -> None:
    """``transact`` only ever issues ``TransactWriteItems``, which reports a
    rejected guard as a cancellation -- so this single-item error is not expected
    here at all.

    It is still mapped, and still tested, because "cannot happen" is exactly the
    assumption that makes property 1 fail silently if it turns out to be wrong:
    no caller of ``transact`` has an ``except``, so the cost of being mistaken is
    every use case breaking at once. Mapped through the same re-check as a
    reasons-less cancellation rather than by assuming which write it concerned,
    which is only knowable when there is exactly one.
    """
    with dynamo() as (store, client):
        assert store.transact([put(KEY, preparation())]) is None
        writes = [
            put(OTHER, preparation()),
            put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST),
        ]
        with patch.object(
            client,
            "transact_write_items",
            side_effect=cancellation(None, code="ConditionalCheckFailedException"),
        ):
            outcome = store.transact(writes)
    assert isinstance(outcome, ConditionFailed)
    assert outcome.key == KEY


def test_a_cancellation_that_is_not_a_guard_is_raised_not_returned() -> None:
    """A conflict is not a lost race.

    Reporting a transaction conflict as ``ConditionFailed`` would render "someone
    else approved first" for a request that never ran -- a confident lie, and one
    the caller would not retry.
    """
    with dynamo() as (store, client):
        with patch.object(
            client,
            "transact_write_items",
            side_effect=cancellation(
                [{"Code": "TransactionConflict"}], code="TransactionCanceledException"
            ),
        ):
            with pytest.raises(ClientError):
                store.transact([put(KEY, preparation(), condition=Condition.MUST_NOT_EXIST)])


def test_a_throttle_is_raised_not_returned() -> None:
    with dynamo() as (store, client):
        with patch.object(
            client,
            "transact_write_items",
            side_effect=cancellation(None, code="ProvisionedThroughputExceededException"),
        ):
            with pytest.raises(ClientError):
                store.transact([put(KEY, preparation())])


def test_more_writes_than_a_transaction_can_hold_is_refused_before_it_is_sent() -> None:
    """Splitting them would silently give up all-or-none, so it is not offered."""
    with dynamo() as (store, client):
        writes = [
            put(("PURCHASE#x", f"ATTEMPT#{index}"), preparation())
            for index in range(TRANSACTION_LIMIT + 1)
        ]
        with pytest.raises(ValueError, match="all-or-none"):
            store.transact(writes)
        assert store.count_matching("PURCHASE#") == 0
