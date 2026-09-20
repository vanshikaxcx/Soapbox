"""Typed ports: what WP-08 needs from the world (WP-08).

These are the contract P4's WP-07 adapters satisfy. They are Protocols rather
than base classes, so an adapter never has to import this module -- it just has
to have the right shape.

The important one is ``StateStore.transact``. WP-08 does not describe *how* the
write is issued; it describes what must commit together and under which
conditions. That list is the whole safety argument for "one approval, one
attempt", so it is expressed as data a reviewer can read rather than as a
sequence of calls buried in a use case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable

from pydantic import Field

from services.domain.catalog import Observation
from services.domain.errors import DomainError
from services.domain.ids import Id, Record
from services.domain.money import Charge

#: A storage key. Two parts so it maps onto DynamoDB's PK/SK without this module
#: knowing anything about DynamoDB.
Key = tuple[str, str]


class Action(StrEnum):
    """Cedar action names P4 must model. Named here so both sides agree."""

    CREATE_PURCHASE = "CreatePurchase"
    READ_PURCHASE = "ReadPurchase"
    ACCEPT_PREPARATION = "AcceptPreparation"
    APPROVE_PURCHASE = "ApprovePurchase"
    CANCEL_PURCHASE = "CancelPurchase"


class Condition(StrEnum):
    NONE = "none"
    MUST_NOT_EXIST = "must_not_exist"
    VERSION_MUST_BE = "version_must_be"


class Write(Record):
    """One item in a transaction, with the condition that guards it."""

    key: Key
    item: object = None
    condition: Condition = Condition.NONE
    expected_version: int | None = None
    #: Why this write exists, in one phrase. Surfaces in failures and in review.
    reason: str = Field(min_length=1, max_length=120)

    model_config = Record.model_config | {"arbitrary_types_allowed": True}


@dataclass(frozen=True, slots=True)
class ConditionFailed(DomainError):
    """A transaction did not commit because a guard rejected it.

    Carries which write failed and why, so a caller can tell "someone else
    approved first" apart from "someone else cancelled first" without guessing.
    """

    code: ClassVar[str] = "condition_failed"
    key: Key
    reason: str


def reject_duplicate_keys(writes: list[Write]) -> None:
    """Refuse a transaction that names the same key twice.

    DynamoDB refuses one outright, so a store that quietly accepted it would
    let a transaction pass in tests and fail in production -- the exact class of
    difference the conformance suite exists to eliminate. It raises rather than
    returning ``ConditionFailed`` because a malformed transaction is a bug in
    the caller, not a lost race: there is no 409 to render and nothing to retry.

    Lives on the port because it is a property of a list of ``Write``, not of
    any one store, and both implementations must apply it identically.
    """
    seen: set[Key] = set()
    for write in writes:
        if write.key in seen:
            raise ValueError(
                f"transaction writes {write.key} twice; a transaction must name each key once"
            )
        seen.add(write.key)


@runtime_checkable
class Clock(Protocol):
    """Time enters the application layer here and nowhere else.

    The domain takes ``now`` as an argument; this is where that argument comes
    from, so tests can move time without touching a rule.
    """

    def now(self) -> datetime: ...


@runtime_checkable
class IdFactory(Protocol):
    """Identifier generation, injected so tests are deterministic."""

    def new_id(self, prefix: str) -> str: ...


@runtime_checkable
class StateStore(Protocol):
    """Canonical state. DynamoDB in production, a dict in tests."""

    def get(self, key: Key) -> object | None: ...

    def transact(self, writes: list[Write]) -> None | ConditionFailed:
        """Commit every write or none of them.

        Returning ``ConditionFailed`` is a normal outcome, not an exception: a
        lost approve/cancel race is an expected event that the caller turns into
        a 409, so it is a value like any other domain error.
        """
        ...

    def keys_matching(self, prefix: str) -> list[Key]:
        """Every key whose *partition* begins with ``prefix``, in sorted order.

        Stated on the port because production already depends on it: the
        operator's effect counts are read back out of committed state rather
        than kept as a running total, so a restart cannot lose a count and a
        retry cannot inflate one. An adapter written against a port that
        omitted this would type-check and then fail the first time an operator
        asked -- which is the failure this line exists to make impossible.

        Sorted so that two stores with the same contents answer identically;
        an order that depends on the storage engine is not a contract.
        """
        ...

    def count_matching(self, prefix: str) -> int:
        """How many keys match, without the caller holding any of them.

        Separate from ``keys_matching`` so a store that can count more cheaply
        than it can list is free to, and so a caller that wants only the number
        cannot accidentally pull an unbounded result set into memory to get it.
        """
        ...


def read[T](store: StateStore, key: Key, kind: type[T]) -> T | None:
    """Read a record and narrow it to the type the caller expects.

    The port returns ``object`` because an adapter cannot know what lives at a
    key. Rather than repeat an isinstance check at every call site -- and
    silently skip it at one of them -- narrowing happens here, and a record of
    the wrong shape reads as absent. Refusing to act on an unexpected record is
    the safe failure; duck-typing into it is not.
    """
    value = store.get(key)
    return value if isinstance(value, kind) else None


@runtime_checkable
class MerchantPort(Protocol):
    """P2's connectors, behind a deadline. WP-08 only ever sees this shape."""

    def refresh(
        self, location: str, sku: str, deadline_seconds: int
    ) -> Observation | DomainError: ...

    def assess_fees(
        self, location: str, merchant_id: str, line_hash: str, deadline_seconds: int
    ) -> tuple[Charge, ...] | DomainError: ...


@runtime_checkable
class PolicyPort(Protocol):
    """Cedar. Authorization is not consent, and this answers only the first."""

    def allows(self, owner_id: Id, action: Action, purchase_id: Id) -> bool: ...
