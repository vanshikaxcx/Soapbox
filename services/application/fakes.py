"""Deterministic in-memory adapters (WP-08).

Test-only. P4's WP-07 owns the real DynamoDB, Step Functions and Cedar
adapters; these exist so the whole P3 lane is buildable and provable without
waiting for them, and so the same contract tests can run against both.

``MemoryStore`` implements real conditional semantics -- must-not-exist and
version-must-be, all-or-none -- because the safety argument for "one approval,
one attempt" is entirely about those conditions. A fake that just wrote
everything would make the tests meaningless.

It also carries a ``before_transact`` hook. That is what lets a test interleave
two callers deterministically at the exact moment that matters: after both have
read, before either has committed. Without it, concurrency tests are either
sleep-based and flaky, or they only ever test the sequential case.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import datetime, timedelta

from services.application.ports import (
    Action,
    Condition,
    ConditionFailed,
    Key,
    Write,
)
from services.domain.catalog import Observation
from services.domain.errors import DomainError
from services.domain.money import Charge


class FixedClock:
    """Time moves only when a test says so."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)

    def set(self, moment: datetime) -> None:
        self._now = moment


class SequentialIds:
    """Predictable identifiers, so an assertion can name one."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def new_id(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}-{self._counts[prefix]:08d}"


class MemoryStore:
    """An in-memory state store with genuine conditional-write semantics."""

    def __init__(self) -> None:
        self._items: dict[Key, object] = {}
        #: Called once, just before a transaction is evaluated. A test uses this
        #: to run a competing caller at the one instant that can expose a race.
        self.before_transact: Callable[[list[Write]], None] | None = None
        self.transactions: list[list[Write]] = []
        self.commits = 0
        self.rejections = 0

    # -- reads -------------------------------------------------------------

    def get(self, key: Key) -> object | None:
        return self._items.get(key)

    def keys_matching(self, prefix: str) -> list[Key]:
        return sorted(k for k in self._items if k[0].startswith(prefix))

    def count_matching(self, prefix: str) -> int:
        return len(self.keys_matching(prefix))

    # -- writes ------------------------------------------------------------

    def transact(self, writes: list[Write]) -> None | ConditionFailed:
        hook, self.before_transact = self.before_transact, None
        if hook is not None:
            hook(writes)

        self.transactions.append(writes)

        for write in writes:
            existing = self._items.get(write.key)
            if write.condition is Condition.MUST_NOT_EXIST and existing is not None:
                self.rejections += 1
                return ConditionFailed(key=write.key, reason=write.reason)
            if write.condition is Condition.VERSION_MUST_BE:
                if existing is None:
                    self.rejections += 1
                    return ConditionFailed(key=write.key, reason=write.reason)
                if getattr(existing, "version", None) != write.expected_version:
                    self.rejections += 1
                    return ConditionFailed(key=write.key, reason=write.reason)

        # Every condition held: apply all of them, or we would not be here.
        for write in writes:
            if write.item is None:
                self._items.pop(write.key, None)
            else:
                self._items[write.key] = write.item
        self.commits += 1
        return None

    # -- test helpers ------------------------------------------------------

    def seed(self, key: Key, item: object) -> None:
        self._items[key] = item

    def snapshot(self) -> dict[Key, object]:
        return copy.copy(self._items)


class AllowAllPolicy:
    def allows(self, owner_id: str, action: Action, purchase_id: str) -> bool:
        return True


class DenyPolicy:
    """Denies one action, so a test can prove the check is actually consulted."""

    def __init__(self, denied: Action) -> None:
        self._denied = denied

    def allows(self, owner_id: str, action: Action, purchase_id: str) -> bool:
        return action is not self._denied


class ScriptedMerchant:
    """A merchant port that answers from a script, including failures.

    WP-08 never waits for a real connector to be green: P2's WP-04 is verified
    separately, and this stands in for it behind the same port.
    """

    def __init__(
        self,
        *,
        observations: dict[str, Observation | DomainError] | None = None,
        fees: tuple[Charge, ...] | DomainError = (),
    ) -> None:
        self._observations = observations or {}
        self._fees = fees
        self.refresh_calls: list[str] = []
        self.fee_calls: int = 0

    def refresh(self, location: str, sku: str, deadline_seconds: int) -> Observation | DomainError:
        self.refresh_calls.append(sku)
        return self._observations[sku]

    def assess_fees(
        self, location: str, merchant_id: str, line_hash: str, deadline_seconds: int
    ) -> tuple[Charge, ...] | DomainError:
        self.fee_calls += 1
        return self._fees


__all__ = [
    "AllowAllPolicy",
    "DenyPolicy",
    "FixedClock",
    "MemoryStore",
    "ScriptedMerchant",
    "SequentialIds",
]
