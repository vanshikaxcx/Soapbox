"""Isolation guarantees around the provider (WP-09 criteria 14, 15).

Two claims, both made structural rather than left as promises:

1. **Recovery has no import path to any write operation.** Not "we were careful"
   -- there is no route through the module graph.
2. **The agent container has no route to the simulator at all.** Arms itself the
   moment P2's package lands.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime

import pytest

from services.application.fakes import FixedClock, SequentialIds
from services.application.provider_ports import ProviderReadPort, ProviderWritePort
from services.simulator.adapter import ReadOnlyProvider, SimulatorProvider
from services.simulator.operations import Simulator

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Every verb that can change what a provider has recorded.
WRITE_VERBS = {"submit", "create_order", "seed_refund", "set_scenario"}


def _a_simulator() -> Simulator:
    """A real one: this test reads the wrapper's surface, never calls through."""
    return Simulator(
        clock=FixedClock(datetime(2026, 9, 15, 12, 0, tzinfo=UTC)), ids=SequentialIds()
    )


def _module_imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
    return modules


# -- the read port genuinely cannot write ----------------------------------


def test_the_read_port_declares_no_write_verb() -> None:
    surface = {n for n in dir(ProviderReadPort) if not n.startswith("_")}
    assert not (surface & WRITE_VERBS)


def test_the_read_only_provider_has_no_write_verb_on_it() -> None:
    """Not hidden, not raising -- simply absent."""
    surface = {n for n in dir(ReadOnlyProvider) if not n.startswith("_")}
    assert not (surface & WRITE_VERBS)
    for verb in WRITE_VERBS:
        # The wrapped provider is never called here; only the surface is read.
        assert not hasattr(ReadOnlyProvider(SimulatorProvider(_a_simulator())), verb)


def test_the_write_port_is_a_strict_superset_of_the_read_port() -> None:
    """So anything handed a write port can still be read from."""
    read = {n for n in dir(ProviderReadPort) if not n.startswith("_")}
    write = {n for n in dir(ProviderWritePort) if not n.startswith("_")}
    assert read <= write
    assert WRITE_VERBS & write


def test_reconcile_never_calls_a_write_verb() -> None:
    """Reconcile reads original references. It creates nothing, ever."""
    module = REPO / "services" / "application" / "reconcile.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (called & WRITE_VERBS), f"reconcile calls {sorted(called & WRITE_VERBS)}"


def test_reconcile_imports_only_the_read_side_of_the_provider() -> None:
    """The guarantee is a property of the import graph, not of good intentions."""
    module = REPO / "services" / "application" / "reconcile.py"
    source = module.read_text(encoding="utf-8")
    for forbidden in ("ProviderWritePort", "SubmitRequest", "OrderRequest"):
        assert forbidden not in source, (
            f"reconcile references {forbidden}; it must not be able to write"
        )


# -- the application never depends on the simulator ------------------------


#: Production modules only. Tests may wire concrete adapters; production code
#: may not, and filtering here keeps the skip list meaningful rather than noisy.
APPLICATION_MODULES = sorted(
    p for p in (REPO / "services" / "application").glob("*.py") if not p.name.endswith("_test.py")
)


@pytest.mark.parametrize("path", APPLICATION_MODULES, ids=lambda p: p.name)
def test_no_application_module_imports_the_simulator(path: pathlib.Path) -> None:
    """The application knows ports. The simulator implements them, not the reverse."""
    offending = {m for m in _module_imports(path) if m.startswith("services.simulator")}
    assert not offending, (
        f"{path.name} imports {sorted(offending)}; depend on provider_ports instead "
        "so a second provider could be added without touching this file"
    )


def test_the_adapter_is_the_only_place_that_knows_both_vocabularies() -> None:
    adapter = REPO / "services" / "simulator" / "adapter.py"
    imports = _module_imports(adapter)
    assert any(m.startswith("services.application") for m in imports)
    assert any(m.startswith("services.simulator") for m in imports)


# -- no agent tool can reach the provider ----------------------------------


def test_no_agent_module_imports_the_simulator() -> None:
    """Arms automatically when P2's WP-04 package appears."""
    agent = REPO / "services" / "agent"
    if not agent.exists():
        pytest.skip(
            "services/agent does not exist yet (P2's WP-04). This guard starts "
            "enforcing the moment it does -- worth telling P2 it is here."
        )
    for path in agent.rglob("*.py"):
        offending = {
            m
            for m in _module_imports(path)
            if m.startswith(("services.simulator", "services.application.purchase"))
        }
        assert not offending, f"{path.name} imports {sorted(offending)}"


# -- and the simulator has no opinion about our domain ---------------------


def test_the_simulator_does_not_know_what_a_purchase_is() -> None:
    """It is a stand-in for a third party: keys, amounts and its own ledger.

    The check names the purchase model specifically rather than banning the
    application package outright. A provider integration legitimately speaks the
    callback envelope -- that is the contract both sides agreed -- but it has no
    business knowing that a ProofPath purchase exists, or what state one is in.
    """
    forbidden = (
        "services.domain.purchase",
        "services.application.purchase",
        "services.application.checkout",
        "services.application.reconcile",
        "services.application.cases",
        "services.application.operator",
    )
    for path in (REPO / "services" / "simulator").glob("*.py"):
        if path.name.endswith("_test.py") or path.name == "adapter.py":
            continue
        offending = {m for m in _module_imports(path) if m.startswith(forbidden)}
        assert not offending, (
            f"{path.name} imports {sorted(offending)}; a real provider would not "
            "know what a ProofPath purchase is"
        )


def test_the_callback_sender_speaks_only_the_agreed_envelope() -> None:
    """What it may borrow from us is the contract, and nothing beyond it."""
    sender = REPO / "services" / "simulator" / "callback_sender.py"
    application_imports = {
        m for m in _module_imports(sender) if m.startswith("services.application")
    }
    assert application_imports <= {"services.application.callbacks"}, (
        f"the sender reaches into {sorted(application_imports)}; it may only use "
        "the callback envelope"
    )


def test_only_the_simulator_writes_its_own_ledger() -> None:
    """Grep-with-an-AST: nothing outside constructs a ledger record."""
    offenders: list[str] = []
    for area in ("application", "domain"):
        for path in (REPO / "services" / area).glob("*.py"):
            if path.name.endswith("_test.py"):
                continue
            source = path.read_text(encoding="utf-8")
            if "PaymentRecord(" in source or "OrderRecord(" in source:
                offenders.append(f"{area}/{path.name}")
    assert not offenders, f"{offenders} build ledger records; only the simulator may"


def test_the_simulator_holds_no_credential_shaped_field() -> None:
    """Nothing here has a card number to leak, by construction."""
    from services.simulator.ledger import OrderRecord, PaymentRecord, RefundRecord

    forbidden = ("card", "pan", "cvv", "otp", "pin", "token", "vpa", "upi", "account")
    for model in (PaymentRecord, OrderRecord, RefundRecord):
        for name in model.model_fields:
            assert not any(word in name.lower() for word in forbidden), (
                f"{model.__name__}.{name} looks like a credential"
            )


def test_a_simulator_can_be_constructed_without_touching_our_store() -> None:
    """It owns its ledger. Nothing else can write to it."""
    import inspect

    parameters = set(inspect.signature(Simulator.__init__).parameters)
    assert "store" not in parameters
    assert parameters >= {"clock", "ids"}
