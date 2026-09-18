"""Domain error taxonomy (WP-02).

Errors are *returned*, never raised, for every expected outcome: a conflict, an
expiry, an unavailable merchant, an illegal transition. Raising is reserved for
programming errors, which is why the canonical encoder raises on a float.

Each error carries a stable ``code`` that handlers map to an HTTP status and
that P1 keys user-facing copy from. Errors carry structured fields only -- enum
values, IDs, amounts -- and never prose, so all wording stays in the UI layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class DomainError:
    """Base of the closed error union. Never instantiated directly."""

    code: ClassVar[str] = "domain_error"


# -- units and matching ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class IncompatibleUnits(DomainError):
    code: ClassVar[str] = "incompatible_units"
    from_dimension: str
    to_dimension: str


@dataclass(frozen=True, slots=True)
class HardAttributeUnsatisfied(DomainError):
    code: ClassVar[str] = "hard_attribute_unsatisfied"
    attribute: str
    required: str
    observed: str | None


@dataclass(frozen=True, slots=True)
class SubstitutionNotPermitted(DomainError):
    code: ClassVar[str] = "substitution_not_permitted"
    kind: str
    flexibility: str


@dataclass(frozen=True, slots=True)
class OverbuyLimitExceeded(DomainError):
    code: ClassVar[str] = "overbuy_limit_exceeded"
    required_base_units: int
    selected_base_units: int
    limit_bp: int


@dataclass(frozen=True, slots=True)
class MixedModeComparison(DomainError):
    code: ClassVar[str] = "mixed_mode_comparison"
    left_mode: str
    right_mode: str


@dataclass(frozen=True, slots=True)
class BudgetExceeded(DomainError):
    code: ClassVar[str] = "budget_exceeded"
    budget_paise: int
    total_paise: int


# -- preparation, quote, approval -----------------------------------------


@dataclass(frozen=True, slots=True)
class PreparationExpired(DomainError):
    code: ClassVar[str] = "preparation_expired"
    preparation_id: str


@dataclass(frozen=True, slots=True)
class DiffNotAccepted(DomainError):
    code: ClassVar[str] = "diff_not_accepted"
    preparation_id: str


@dataclass(frozen=True, slots=True)
class DiffHashMismatch(DomainError):
    code: ClassVar[str] = "diff_hash_mismatch"
    expected: str
    submitted: str


@dataclass(frozen=True, slots=True)
class QuoteExpired(DomainError):
    code: ClassVar[str] = "quote_expired"
    quote_id: str


@dataclass(frozen=True, slots=True)
class QuoteHashMismatch(DomainError):
    code: ClassVar[str] = "quote_hash_mismatch"
    expected: str
    submitted: str


@dataclass(frozen=True, slots=True)
class QuoteNotConstructible(DomainError):
    """An exact quote needs an exact total; estimated and unknown both block it."""

    code: ClassVar[str] = "quote_not_constructible"
    reason: str
    charge_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApprovalAlreadyConsumed(DomainError):
    code: ClassVar[str] = "approval_already_consumed"
    approval_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class ApprovalExpired(DomainError):
    code: ClassVar[str] = "approval_expired"
    approval_id: str


# -- purchase and attempt --------------------------------------------------


@dataclass(frozen=True, slots=True)
class PurchaseAlreadyClaimed(DomainError):
    code: ClassVar[str] = "purchase_already_claimed"
    purchase_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class AttemptBlockedByExposure(DomainError):
    code: ClassVar[str] = "attempt_blocked_by_exposure"
    payment_state: str
    dispatch_state: str


@dataclass(frozen=True, slots=True)
class PaymentKeyConflict(DomainError):
    """Same provider key, different payload. No effect is recorded."""

    code: ClassVar[str] = "payment_key_conflict"
    payment_key: str


# -- concurrency -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionConflict(DomainError):
    code: ClassVar[str] = "version_conflict"
    expected: int
    actual: int


@dataclass(frozen=True, slots=True)
class IdempotencyPayloadMismatch(DomainError):
    code: ClassVar[str] = "idempotency_payload_mismatch"
    key: str


@dataclass(frozen=True, slots=True)
class IllegalTransition(DomainError):
    code: ClassVar[str] = "illegal_transition"
    machine: str
    current: str
    event: str


# -- provider facts --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContradictoryProviderFact(DomainError):
    """Two terminal facts disagree. Never applied; the provider must be queried."""

    code: ClassVar[str] = "contradictory_provider_fact"
    machine: str
    current: str
    incoming: str


@dataclass(frozen=True, slots=True)
class FactIgnoredStale(DomainError):
    """Not a failure: an older or non-terminal fact correctly did nothing."""

    code: ClassVar[str] = "fact_ignored_stale"
    machine: str
    current: str
    incoming: str


@dataclass(frozen=True, slots=True)
class InvalidRecord(DomainError):
    code: ClassVar[str] = "invalid_record"
    record: str
    detail: str


def is_error(value: object) -> bool:
    """True when a domain function returned an error rather than a value."""
    return isinstance(value, DomainError)


#: The surface other packages may depend on. Adding to it is a deliberate
#: act: WP-02 is the sole home of these rules, so a new export is a new rule.
__all__ = [
    "ApprovalAlreadyConsumed",
    "ApprovalExpired",
    "AttemptBlockedByExposure",
    "BudgetExceeded",
    "ContradictoryProviderFact",
    "DiffHashMismatch",
    "DiffNotAccepted",
    "DomainError",
    "FactIgnoredStale",
    "HardAttributeUnsatisfied",
    "IdempotencyPayloadMismatch",
    "IllegalTransition",
    "IncompatibleUnits",
    "InvalidRecord",
    "MixedModeComparison",
    "OverbuyLimitExceeded",
    "PaymentKeyConflict",
    "PreparationExpired",
    "PurchaseAlreadyClaimed",
    "QuoteExpired",
    "QuoteHashMismatch",
    "QuoteNotConstructible",
    "SubstitutionNotPermitted",
    "VersionConflict",
    "is_error",
]
