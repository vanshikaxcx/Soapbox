"""Public API snapshot (WP-02 exit gate).

The exit gate is that P2, P3 and P4 agree these are the *sole* canonical rules.
This test makes the surface those packages depend on explicit: adding a rule is a
deliberate edit here, and a reviewer of WP-06/08/09/10 can read this list to see
at a glance whether a rule was reimplemented somewhere it should have been
imported from.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

#: module -> the callables and types other packages are entitled to depend on.
PUBLIC_API: dict[str, set[str]] = {
    "services.domain.errors": {
        "DomainError",
        "is_error",
        "IncompatibleUnits",
        "HardAttributeUnsatisfied",
        "SubstitutionNotPermitted",
        "OverbuyLimitExceeded",
        "MixedModeComparison",
        "BudgetExceeded",
        "PreparationExpired",
        "DiffNotAccepted",
        "DiffHashMismatch",
        "QuoteExpired",
        "QuoteHashMismatch",
        "QuoteNotConstructible",
        "ApprovalAlreadyConsumed",
        "ApprovalExpired",
        "PurchaseAlreadyClaimed",
        "AttemptBlockedByExposure",
        "PaymentKeyConflict",
        "VersionConflict",
        "IdempotencyPayloadMismatch",
        "IllegalTransition",
        "ContradictoryProviderFact",
        "FactIgnoredStale",
        "InvalidRecord",
        "VoiceSessionExpired",
        "VoiceSessionAlreadyResolved",
    },
    "services.domain.ids": {
        "ID_PATTERN",
        "Id",
        "Digest",
        "Mode",
        "Record",
        "Timestamped",
        "is_valid_id",
        "utc",
    },
    "services.domain.units": {
        "Dimension",
        "Unit",
        "Quantity",
        "convert",
        "add",
        "scale",
        "dimension_of",
        "base_units_per",
    },
    "services.domain.money": {
        "Currency",
        "Confidence",
        "ChargeKind",
        "Money",
        "MoneyDelta",
        "Amount",
        "Charge",
        "Totals",
        "BudgetCheck",
        "compute_totals",
        "check_budget",
        "total_of",
        "unit_rate",
        "difference",
        "worst",
    },
    "services.domain.canonical": {
        "CANON_SCHEME",
        "ALL_TAGS",
        "CanonicalEncodingError",
        "TAG_QUOTE",
        "TAG_DIFF",
        "TAG_LINES",
        "TAG_IDEMPOTENCY",
        "TAG_APPROVAL_ID",
        "TAG_PAYMENT_KEY",
        "TAG_PAYMENT_REQUEST",
        "TAG_ORDER_KEY",
        "TAG_BODY",
        "TAG_VOICE_TRANSCRIPT",
        "canonical_json",
        "digest",
        "body_hash",
    },
    "services.domain.keys": {
        "approval_id",
        "payment_key",
        "payment_request_hash",
        "order_key",
        "quote_hash",
        "idempotency_request_hash",
        "line_hash",
        "diff_hash",
    },
    "services.domain.transitions": {
        "PaymentState",
        "OrderState",
        "RefundState",
        "DispatchState",
        "ApprovalState",
        "ClaimState",
        "JobState",
        "InboxState",
        "CaseState",
        "PaymentEvent",
        "OrderEvent",
        "RefundEvent",
        "DispatchEvent",
        "ApprovalEvent",
        "ClaimEvent",
        "JobEvent",
        "InboxEvent",
        "CaseEvent",
        "PAYMENT_TABLE",
        "ORDER_TABLE",
        "REFUND_TABLE",
        "DISPATCH_TABLE",
        "APPROVAL_TABLE",
        "CLAIM_TABLE",
        "JOB_TABLE",
        "INBOX_TABLE",
        "CASE_TABLE",
        "MACHINES",
        "apply",
        "is_terminal",
        "StateMachineMisuse",
    },
    "services.domain.provider": {
        "Observed",
        "PaymentFacts",
        "OrderFacts",
        "RefundFacts",
        "Current",
        "Applied",
        "ApplyResult",
        "apply_payment_facts",
        "apply_order_facts",
        "apply_refund_facts",
    },
    "services.domain.purchase": {
        "PREPARATION_FRESHNESS_SECONDS",
        "QUOTE_LIFETIME_SECONDS",
        "ChangeKind",
        "Change",
        "Diff",
        "build_diff",
        "Preparation",
        "QuoteWindow",
        "AttemptSnapshot",
        "PurchaseSnapshot",
        "EXPOSED_PAYMENT_STATES",
        "is_fresh",
        "is_quote_live",
        "quote_window",
        "can_build_quote",
        "check_quote_live",
        "has_unresolved_exposure",
        "may_create_attempt",
        # the commerce core: what WP-08 writes and WP-09 reads
        "QuoteLine",
        "CheckoutQuote",
        "Approval",
        "Attempt",
        "ProviderLookup",
        "Purchase",
        "build_attempt_and_lookup",
    },
    "services.domain.search": {
        "MerchantProgress",
        "Search",
        "SearchStatus",
        "is_current",
    },
    "services.domain.basket": {
        "Comparison",
        "BasketCost",
        "compare_baskets",
        "cheapest",
        "cheaper_of",
        "BasketLine",
        "FeeAssessment",
        "Basket",
        "build_basket",
    },
    "services.domain.intent": {
        "MAX_ITEMS",
        "Flexibility",
        "DeliveryConstraint",
        "Item",
        "Intent",
        "Preferences",
        "UsualBasket",
        "revise",
        "touch",
        "is_current_revision",
        "to_intent_items",
    },
    "services.domain.catalog": {
        "OVERBUY_LIMIT_BP",
        "BP_DENOMINATOR",
        "MAX_SEARCH_BASE_UNITS",
        "ExtractionStatus",
        "Observation",
        "SubstitutionKind",
        "Substitution",
        "PackOption",
        "PackSelection",
        "satisfies_hard_attributes",
        "check_substitution",
        "select_packs",
        "is_usable",
    },
    "services.domain.conversation": {
        "InputKind",
        "Speaker",
        "QuestionKind",
        "PURCHASE_MUTATING_QUESTION_KINDS",
        "QuestionStatus",
        "VoiceSessionStatus",
        "Conversation",
        "Turn",
        "Question",
        "VoiceSession",
        "is_expired",
        "binding_is_current",
        "may_submit",
    },
    "services.domain.evidence": {
        "FactKind",
        "EvidenceKind",
        "InboxEvent",
        "Evidence",
        "MissingFact",
        "Case",
        "is_duplicate",
        "is_conflicting",
    },
    "services.domain.jobs": {
        "JobType",
        "PublicationState",
        "Job",
        "OutboxEvent",
        "DuplicateDelivery",
        "retry",
        "start",
        "succeed",
        "fail",
        "resolve_delivery",
    },
}


def _exported(module_name: str) -> set[str]:
    """The surface the module *declares*, not one inferred from its namespace.

    Inference was the first attempt and it was wrong in two ways: a re-exported
    string constant has no ``__module__`` to filter on, and a union type alias
    reports someone else's. Declaring ``__all__`` makes the surface a decision
    rather than an accident of how the imports happen to be written.
    """
    module = importlib.import_module(module_name)
    declared = getattr(module, "__all__", None)
    assert declared is not None, f"{module_name} does not declare __all__"
    return set(declared)


@pytest.mark.parametrize("module_name", sorted(PUBLIC_API), ids=lambda n: n.split(".")[-1])
def test_every_declared_name_actually_exists(module_name: str) -> None:
    """__all__ can lie. This is what stops it."""
    module = importlib.import_module(module_name)
    for name in _exported(module_name):
        assert hasattr(module, name), f"{module_name}.__all__ names {name}, which is absent"


@pytest.mark.parametrize("module_name", sorted(PUBLIC_API), ids=lambda n: n.split(".")[-1])
def test_no_module_is_exported_as_public_api(module_name: str) -> None:
    module = importlib.import_module(module_name)
    for name in _exported(module_name):
        assert not inspect.ismodule(getattr(module, name)), (
            f"{module_name}.__all__ exports the module {name}"
        )


@pytest.mark.parametrize("module_name", sorted(PUBLIC_API), ids=lambda n: n.split(".")[-1])
def test_the_public_surface_matches_the_snapshot(module_name: str) -> None:
    actual = _exported(module_name)
    expected = PUBLIC_API[module_name]

    added = actual - expected
    removed = expected - actual

    assert not added, (
        f"{module_name} exports {sorted(added)} which is not in the snapshot. "
        "Adding a canonical rule is deliberate: add it here and tell P2 and P4."
    )
    assert not removed, (
        f"{module_name} no longer exports {sorted(removed)}. Other packages may "
        "depend on it; removing it is a breaking change."
    )


def test_every_domain_module_is_covered_by_the_snapshot() -> None:
    import pathlib

    package = pathlib.Path(__file__).parent
    modules = {
        f"services.domain.{p.stem}"
        for p in package.glob("*.py")
        if not p.name.endswith("_test.py") and p.stem not in {"__init__", "vectors_data"}
    }
    assert modules == set(PUBLIC_API), (
        "a domain module has no public-API snapshot; add it to PUBLIC_API"
    )
