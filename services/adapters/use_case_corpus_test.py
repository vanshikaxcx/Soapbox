"""AC-5: WP-08 and WP-09's own suites, run against DynamoDB (WP-07).

This is the most valuable test in the package and it contains almost no
assertions of its own. It takes the test functions WP-08 and WP-09 already
wrote -- every rule about approvals, attempts, quotes, claims, cancellation
races, checkout and reconciliation -- swaps the store underneath them for the
real adapter, and runs them again.

Their value is precisely that **they were not written with an adapter in
mind**. A test written to exercise a DynamoDB adapter tends to check the things
its author already knew to worry about. These check what the business rules
actually need, and they were passing against a fake long before this adapter
existed, so if the adapter is not a faithful substitute they are the tests most
likely to notice.

The swap is one class attribute, ``World.store_factory``, on the two ``World``
classes the whole WP-08/09 surface funnels through: ``checkout_test``,
``cases_test``, ``operator_test`` and the regression suites all build on one of
them. Nothing else about those tests changes.

**What is excluded, and why.** Two kinds, and both are excluded by reading the
test's own source rather than by a list somebody has to remember to update:

* tests that reach for ``world.memory`` -- the fake's interleaving hook, its
  commit counter, its raw item dict. They are *about* the fake. "Did you commit
  exactly once" and "run this competing caller between the read and the write"
  are not questions DynamoDB can be asked, and a conformance run that pretended
  otherwise would be testing the harness.
* tests that build a ``MemoryStore()`` of their own in the test body, which the
  factory swap cannot reach. Including them would inflate the count with tests
  that never touched the adapter at all.

Both lists are asserted to be non-empty and are reported by name, so a silent
drift to "nothing runs against DynamoDB any more" fails rather than passes.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from itertools import count
from types import ModuleType

import boto3
import pytest
from moto import mock_aws

import services.api.purchases_test as api_purchases_suite
import services.application.cases_test as cases_suite
import services.application.checkout_regressions_test as checkout_regressions_suite
import services.application.checkout_test as checkout_suite
import services.application.consent_guards_test as consent_guards_suite
import services.application.operator_test as operator_suite
import services.application.prepare_regressions_test as prepare_regressions_suite
import services.application.prepare_test as prepare_suite
import services.application.purchase_test as purchase_suite
from services.adapters.dynamo_state_store import (
    PARTITION_ATTRIBUTE,
    SORT_ATTRIBUTE,
    DynamoStateStore,
)
from services.application.ports import StateStore

TABLE = "proofpath-corpus"
REGION = "ap-south-1"

#: Every WP-08/09 module whose tests reach a store. They all build on one of the
#: two ``World`` classes, directly or through ``CheckoutWorld``.
SUITES: tuple[ModuleType, ...] = (
    prepare_suite,
    prepare_regressions_suite,
    purchase_suite,
    checkout_suite,
    checkout_regressions_suite,
    cases_suite,
    operator_suite,
    consent_guards_suite,
    api_purchases_suite,
)

#: The two classes the swap has to reach.
WORLDS = (prepare_suite.World, purchase_suite.World)

#: Source markers for the two kinds of test the swap cannot carry.
ABOUT_THE_FAKE = ".memory."
BUILDS_ITS_OWN = "MemoryStore("


@contextmanager
def dynamo_backend() -> Iterator[Callable[[], StateStore]]:
    """A factory handing out a *fresh* DynamoDB table per ``World``.

    Fresh per call, not per test, because that is what it is replacing: every
    ``World()`` builds its own ``MemoryStore()``, so a test that builds two of
    them is relying on the second knowing nothing about the first. A factory
    that returned one shared store would break exactly those tests -- and it
    would look like an adapter defect rather than a harness one. Two tests said
    so before this was fixed.

    Everything is thrown away with the ``mock_aws`` context at the end of the
    test, tables included.
    """
    with mock_aws():
        client = boto3.client(
            "dynamodb",
            region_name=REGION,
            aws_access_key_id="corpus",
            aws_secret_access_key="corpus",
            aws_session_token="corpus",
        )
        tables = count()

        def build() -> StateStore:
            name = f"{TABLE}-{next(tables)}"
            client.create_table(
                TableName=name,
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
            return DynamoStateStore(client=client, table_name=name)

        yield build


def _source(test: Callable[[], None]) -> str:
    try:
        return inspect.getsource(test)
    except OSError:  # pragma: no cover - every test here has source
        return ""


def _runnable(test: object) -> bool:
    """Whether the corpus can call this test directly.

    Only zero-argument functions: anything taking a fixture needs pytest to
    supply it, and re-implementing that here would be inventing a second test
    runner rather than reusing a suite.
    """
    if not callable(test) or not inspect.isfunction(test):
        return False
    return not inspect.signature(test).parameters


def collect() -> tuple[list[tuple[str, Callable[[], None]]], list[str], list[str]]:
    included: list[tuple[str, Callable[[], None]]] = []
    about_the_fake: list[str] = []
    builds_its_own: list[str] = []
    for module in SUITES:
        for name, test in sorted(vars(module).items()):
            if not name.startswith("test_") or not _runnable(test):
                continue
            label = f"{module.__name__.rsplit('.', 1)[-1]}::{name}"
            source = _source(test)
            if ABOUT_THE_FAKE in source:
                about_the_fake.append(label)
            elif BUILDS_ITS_OWN in source:
                builds_its_own.append(label)
            else:
                included.append((label, test))
    return included, about_the_fake, builds_its_own


CORPUS, ABOUT_THE_FAKE_TESTS, OWN_STORE_TESTS = collect()


def test_the_corpus_is_not_empty() -> None:
    """The guard that stops this whole file quietly becoming a no-op.

    If a refactor renamed ``World`` or moved the suites, ``collect()`` would
    return nothing and every parametrized case below would vanish -- leaving a
    green run that proves the adapter against no rules at all.
    """
    assert len(CORPUS) >= 100, f"only {len(CORPUS)} WP-08/09 tests reached the adapter"


def test_the_exclusions_are_real_and_named() -> None:
    """Both exclusion reasons must actually apply to something.

    An empty list would mean the detection had stopped working, and every
    excluded test would have been silently swept into the run instead.
    """
    assert ABOUT_THE_FAKE_TESTS, "nothing was excluded for reading the fake's bookkeeping"
    assert OWN_STORE_TESTS, "nothing was excluded for building its own store"


def test_no_test_is_both_included_and_excluded() -> None:
    labels = {label for label, _ in CORPUS}
    assert not labels & set(ABOUT_THE_FAKE_TESTS)
    assert not labels & set(OWN_STORE_TESTS)


@pytest.mark.parametrize(("label", "test"), CORPUS, ids=[label for label, _ in CORPUS])
def test_the_wp08_and_wp09_corpus_passes_against_dynamodb(
    label: str, test: Callable[[], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One of WP-08/09's own tests, unaltered, against the real store."""
    with dynamo_backend() as build:
        for world in WORLDS:
            monkeypatch.setattr(world, "store_factory", staticmethod(build))
        test()


def test_the_swap_actually_reaches_the_worlds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof that the run above is not passing because nothing changed.

    Without this, a ``store_factory`` that silently stopped being consulted
    would leave every case above running happily against the fake and reporting
    a conformance result that was never measured.
    """
    with dynamo_backend() as build:
        for world in WORLDS:
            monkeypatch.setattr(world, "store_factory", staticmethod(build))
        first = purchase_suite.World().store
        second = prepare_suite.World().store
        assert isinstance(first, DynamoStateStore)
        assert isinstance(second, DynamoStateStore)
        assert first is not second, "each World must get its own store, as MemoryStore does"


def test_the_excluded_tests_are_reported_for_review() -> None:
    """Not an assertion so much as a printed record.

    Exclusions decided by a rule are only trustworthy if a reviewer can see what
    the rule caught, so the names are written into the test's own output.
    """
    report = {
        "included": len(CORPUS),
        "about_the_fake": ABOUT_THE_FAKE_TESTS,
        "builds_its_own_store": OWN_STORE_TESTS,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    assert rendered
    print(rendered)
