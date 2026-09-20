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

A ``@pytest.mark.parametrize`` over a single argument is **expanded and run**,
not dropped. It used to be dropped, silently, by a signature check that only
admitted zero-argument functions -- and the six it discarded included
``test_no_scenario_ever_produces_two_effects`` and the other exhaustive
one-effect invariants, which are the tests here least likely to have been
written with an adapter in mind and therefore the most worth running against
one. Anything this cannot expand -- a fixture, several arguments, several marks
-- goes on a third list rather than disappearing.

Every test function in these suites is accounted for in exactly one bucket, and
that is asserted. It is the only check that actually prevents a silent drop:
counting what ran cannot notice what never arrived.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
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


def _is_a_test(test: object) -> bool:
    return callable(test) and inspect.isfunction(test)


def _expand(label: str, test: Callable[..., None]) -> list[tuple[str, Callable[[], None]]] | None:
    """Turn a test into the cases the corpus can call, or ``None`` if it cannot.

    A zero-argument test is one case. A test with exactly one
    ``@pytest.mark.parametrize`` over exactly one argument is one case per
    value -- pytest would run it that way too, and the values are right there on
    the mark. Anything else needs pytest to supply something, and re-inventing
    that here would be building a second test runner rather than reusing a suite.
    """
    parameters = inspect.signature(test).parameters
    if not parameters:
        return [(label, test)]
    marks = [mark for mark in getattr(test, "pytestmark", []) if mark.name == "parametrize"]
    if len(marks) != 1 or len(marks[0].args) < 2:
        return None
    argnames, argvalues = marks[0].args[0], marks[0].args[1]
    names = (
        [name.strip() for name in argnames.split(",")]
        if isinstance(argnames, str)
        else list(argnames)
    )
    if len(names) != 1 or len(parameters) != 1:
        return None
    return [(f"{label}[{value}]", partial(test, value)) for value in argvalues]


def collect() -> tuple[
    list[tuple[str, Callable[[], None]]], list[str], list[str], list[str], list[str]
]:
    included: list[tuple[str, Callable[[], None]]] = []
    included_functions: list[str] = []
    about_the_fake: list[str] = []
    builds_its_own: list[str] = []
    cannot_expand: list[str] = []
    every_function: list[str] = []
    for module in SUITES:
        for name, test in sorted(vars(module).items()):
            if not name.startswith("test_") or not _is_a_test(test):
                continue
            label = f"{module.__name__.rsplit('.', 1)[-1]}::{name}"
            every_function.append(label)
            source = _source(test)
            if ABOUT_THE_FAKE in source:
                about_the_fake.append(label)
                continue
            if BUILDS_ITS_OWN in source:
                builds_its_own.append(label)
                continue
            cases = _expand(label, test)
            if cases is None:
                cannot_expand.append(label)
                continue
            included.extend(cases)
            included_functions.append(label)
    return included, about_the_fake, builds_its_own, cannot_expand, every_function


CORPUS, ABOUT_THE_FAKE_TESTS, OWN_STORE_TESTS, UNEXPANDABLE_TESTS, ALL_TESTS = collect()
INCLUDED_FUNCTIONS = [
    label
    for label in ALL_TESTS
    if label not in {*ABOUT_THE_FAKE_TESTS, *OWN_STORE_TESTS, *UNEXPANDABLE_TESTS}
]


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
    buckets = [
        set(INCLUDED_FUNCTIONS),
        set(ABOUT_THE_FAKE_TESTS),
        set(OWN_STORE_TESTS),
        set(UNEXPANDABLE_TESTS),
    ]
    for index, bucket in enumerate(buckets):
        for other in buckets[index + 1 :]:
            assert not bucket & other, f"a test is in two buckets: {sorted(bucket & other)}"


def test_every_test_in_these_suites_is_accounted_for() -> None:
    """The only check that can notice a silent drop.

    Counting what ran cannot see what never arrived. This compares the buckets
    against every test function in the suites, so a test that stops being
    collected has to show up somewhere rather than simply stop existing -- which
    is exactly how the parametrized ones went missing.
    """
    accounted = {
        *INCLUDED_FUNCTIONS,
        *ABOUT_THE_FAKE_TESTS,
        *OWN_STORE_TESTS,
        *UNEXPANDABLE_TESTS,
    }
    assert accounted == set(ALL_TESTS), f"unaccounted: {sorted(set(ALL_TESTS) - accounted)}"


def test_the_exhaustive_one_effect_invariants_are_included() -> None:
    """Named, because these are the ones that were being dropped.

    They sweep every simulator scenario and assert that none of them produces a
    second effect. They are the tests here least likely to have been written
    with an adapter in mind, and they were the ones the signature check threw
    away.
    """
    functions = set(INCLUDED_FUNCTIONS)
    for expected in (
        "checkout_test::test_no_scenario_ever_produces_two_effects",
        "operator_test::test_effects_never_exceed_dispatches_in_any_scenario",
        "checkout_regressions_test::"
        "test_no_scenario_produces_more_than_one_effect_after_the_rewrite",
    ):
        assert expected in functions, f"{expected} is no longer reaching the adapter"
    assert len(CORPUS) > len(INCLUDED_FUNCTIONS), "a parametrized test expands to several cases"


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
        "included_cases": len(CORPUS),
        "included_functions": len(INCLUDED_FUNCTIONS),
        "about_the_fake": ABOUT_THE_FAKE_TESTS,
        "builds_its_own_store": OWN_STORE_TESTS,
        "cannot_be_expanded": UNEXPANDABLE_TESTS,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    assert rendered
    print(rendered)
