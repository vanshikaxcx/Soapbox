"""Operator controls and effect counts (WP-09 criteria 16, 17).

Two capabilities, both behind the same authorization check:

- **Set a scenario.** The operator tells the simulated provider how to behave
  next, so a fault can be demonstrated on demand rather than waited for.
- **Read effect counts.** Straight off the provider's ledger. This is the number
  that proves the claim -- one approval, one payment effect -- and it is read from
  the provider rather than from our own state, because our state is the thing
  being checked.

A shopper asking for either receives ``404``. Not ``403``: telling someone a
control exists but is not theirs is still telling them it exists, and the whole
demo surface would otherwise be discoverable from a normal account.

Seeding a restricted demo-operator identity so judges can drive the scenarios is
WP-11's job. It must not be done by weakening this check.
"""

from __future__ import annotations

from typing import Protocol

from services.application.ports import StateStore
from services.application.purchase import NotFound
from services.domain.errors import DomainError
from services.domain.ids import Record


class OperatorPolicy(Protocol):
    """Cedar, narrowed to the one question this module asks."""

    def is_operator(self, owner_id: str) -> bool: ...


class EffectLedger[ScenarioT](Protocol):
    """What the operator surface needs from a provider, and nothing more.

    A Protocol rather than the simulator itself: the application layer must not
    import a concrete adapter, and an isolation test enforces that. It also means
    a second provider could be counted the same way.

    ``ScenarioT`` is the provider's own scenario type. It is a type parameter
    rather than a concrete import because the application layer may not name the
    simulator's enum -- doing so would invert the dependency this Protocol exists
    to keep pointing the right way. Variance is inferred: the parameter appears
    only in an argument position, so it is contravariant.

    ``set_scenario`` used to take ``object``, which looked permissive and was in
    fact impossible to satisfy: protocol parameters are contravariant, so an
    implementation accepting only its own ``Scenario`` enum did not conform, and
    a caller holding an ``EffectLedger`` could pass anything at all and fail at
    runtime. The type parameter says the real thing -- each provider names the
    scenario type it accepts -- without naming the simulator here.
    """

    submissions_received: int
    duplicate_submissions_suppressed: int

    def set_scenario(self, scenario: ScenarioT) -> None: ...

    def effect_count(self) -> int: ...

    def order_effect_count(self) -> int: ...

    def rejection_count(self) -> int: ...


class EffectCounts(Record):
    """What the demo displays. Every number comes from the provider's ledger."""

    payment_effects: int = 0
    order_effects: int = 0
    submissions_received: int = 0
    duplicate_submissions_suppressed: int = 0
    rejections: int = 0
    #: How many attempts we actually dispatched. The claim is that this equals
    #: ``payment_effects`` -- any other relationship is the story falling apart.
    attempts_dispatched: int = 0

    @property
    def one_effect_per_attempt(self) -> bool:
        return self.payment_effects == self.attempts_dispatched


class ScenarioSet(Record):
    scenario: str


class OperatorUseCases[ScenarioT]:
    """Operator-only. Every method checks authorization before doing anything."""

    def __init__(
        self, *, store: StateStore, simulator: EffectLedger[ScenarioT], policy: OperatorPolicy
    ) -> None:
        self._store = store
        self._simulator = simulator
        self._policy = policy

    def set_scenario(self, *, owner_id: str, scenario: ScenarioT) -> ScenarioSet | DomainError:
        if not self._is_operator(owner_id):
            return NotFound("demo controls")
        self._simulator.set_scenario(scenario)
        return ScenarioSet(scenario=str(scenario))

    def effect_counts(self, *, owner_id: str) -> EffectCounts | DomainError:
        if not self._is_operator(owner_id):
            return NotFound("demo controls")
        return EffectCounts(
            payment_effects=self._simulator.effect_count(),
            order_effects=self._simulator.order_effect_count(),
            submissions_received=self._simulator.submissions_received,
            duplicate_submissions_suppressed=(self._simulator.duplicate_submissions_suppressed),
            rejections=self._simulator.rejection_count(),
            attempts_dispatched=self._count_dispatched(),
        )

    def _count_dispatched(self) -> int:  # noqa: D401
        """Attempts that actually reached a provider call.

        Counted from the store rather than from a running total, so a restart
        cannot lose it and a double-count cannot creep in.
        """
        from services.domain.purchase import Attempt
        from services.domain.transitions import DispatchState

        dispatched = 0
        for key in self._store.keys_matching("PURCHASE#"):  # type: ignore[attr-defined]
            if "ATTEMPT#" not in key[1]:
                continue
            attempt = self._store.get(key)
            if isinstance(attempt, Attempt) and attempt.dispatch is DispatchState.STARTED:
                dispatched += 1
        return dispatched

    def _is_operator(self, owner_id: str) -> bool:
        return bool(self._policy.is_operator(owner_id))


__all__ = ["EffectCounts", "OperatorUseCases", "ScenarioSet"]
