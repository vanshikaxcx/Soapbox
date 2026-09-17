"""Nothing but the approve control can create an approval (WP-08 criterion 13).

The spec names three independent mechanisms. This file asserts the two that are
structural, and arms the third for the moment P2's agent package lands.

The threat is not a malicious shopper. It is a helpful one: a model that decides
"they said yes, I will just approve it", or a replayed transcript that lands on
the approval path. Both are prevented by the same thing -- approval requires a
current quote hash and two current version numbers, which only the card that
displayed them possesses.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from services.application.purchase import PurchaseUseCases
from services.domain.conversation import (
    PURCHASE_MUTATING_QUESTION_KINDS,
    QuestionKind,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


# -- mechanism 1: approval demands things a model does not hold ------------


def test_approval_requires_the_hash_and_both_versions_together() -> None:
    """A model or a replayed transcript does not possess a current hash."""
    parameters = inspect.signature(PurchaseUseCases.approve).parameters
    required = {
        "quote_id",
        "quote_hash",
        "quote_version",
        "expected_purchase_version",
        "owner_id",
        "purchase_id",
        "idempotency",
    }
    assert required <= set(parameters)


def test_every_approval_argument_is_keyword_only() -> None:
    """So no caller can approve by getting positional arguments lucky."""
    parameters = inspect.signature(PurchaseUseCases.approve).parameters
    for name, parameter in parameters.items():
        if name == "self":
            continue
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{name} is positional; approval must be spelled out in full"
        )


def test_no_approval_argument_has_a_default() -> None:
    """A default would let a partially-filled call succeed."""
    parameters = inspect.signature(PurchaseUseCases.approve).parameters
    for name, parameter in parameters.items():
        if name == "self":
            continue
        assert parameter.default is inspect.Parameter.empty, f"{name} has a default"


# -- mechanism 2: no question a shopper answers can mutate a purchase ------


def test_the_purchase_mutating_question_set_is_empty() -> None:
    assert frozenset() == PURCHASE_MUTATING_QUESTION_KINDS


def test_no_question_kind_reads_like_an_approval() -> None:
    for kind in QuestionKind:
        lowered = kind.value.lower()
        for forbidden in ("approve", "pay", "purchase", "checkout", "confirm_order"):
            assert forbidden not in lowered, f"{kind} looks like a payment action"


def test_the_conversation_model_cannot_reach_the_purchase_model() -> None:
    """Structural: an answer handler has no path to a purchase record."""
    source = (REPO / "services" / "domain" / "conversation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "purchase" not in node.module, (
                "conversation imports purchase; an answer could then mutate one"
            )


# -- mechanism 3: no agent tool targets purchase or provider ---------------


def _agent_modules() -> list[pathlib.Path]:
    agent = REPO / "services" / "agent"
    if not agent.exists():
        return []
    return sorted(agent.rglob("*.py"))


def test_no_agent_tool_can_reach_approval_or_payment() -> None:
    """Arms itself the moment P2's WP-04 agent package appears.

    Skipping is honest here rather than comforting: the guard cannot run against
    a package that does not exist, and saying so is better than passing
    vacuously. When P2 lands the tool registry this test starts enforcing.
    """
    modules = _agent_modules()
    if not modules:
        pytest.skip(
            "services/agent does not exist yet (P2's WP-04). This guard activates "
            "automatically when it lands, and P2 should be told it exists."
        )

    forbidden = {"services.application.purchase", "services.domain.purchase", "services.simulator"}
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden, (
                    f"{path.name} imports {node.module}; an agent tool must not be "
                    "able to approve, pay or refund"
                )


# -- and the approval path itself is the only writer of an approval --------


def test_only_the_approve_use_case_constructs_a_consumed_approval() -> None:
    """Grep-with-an-AST: no other module builds an Approval marked consumed."""
    application = REPO / "services" / "application"
    offenders: list[str] = []
    for path in application.glob("*.py"):
        if path.name.endswith("_test.py"):
            continue
        source = path.read_text(encoding="utf-8")
        if "ApprovalState.CONSUMED" not in source:
            continue
        if path.name != "purchase.py":
            offenders.append(path.name)
    assert not offenders, f"{offenders} construct a consumed approval outside approve()"
