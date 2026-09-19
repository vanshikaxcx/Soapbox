"""Dependency-direction guards for the worker layer (WP-07).

The last layer without one. Workers sit at the outside edge: they may depend on
adapters, on the application layer and on the domain, and nothing may depend on
them. The specific mistake this catches is a worker importing ``services.api``
to reuse a response helper, which would make two transports share a shape that
only one of them is contracted to.

The other half is that a worker must not contain a rule. That cannot be asserted
by import alone, but the shape can: a worker parses, calls one use case, and
renders a reply, so it has no business importing the domain's transition tables
or reaching for a clock of its own.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).parent
MODULES = sorted(p for p in PACKAGE.glob("*.py") if not p.name.endswith("_test.py"))

#: Nothing here may be imported by a worker. ``services.api`` is the sharp one:
#: it is a sibling transport, not a library.
FORBIDDEN_PACKAGES = (
    "services.api",
    "services.agent",
    "services.merchants",
    "services.simulator",
)

ALLOWED_STDLIB = {
    "__future__",
    "collections",
    "dataclasses",
    "enum",
    # A worker's input arrives as a JSON string on a queue. Unwrapping it is
    # precisely this layer's job, and the layer above must never see the string.
    "json",
    # A worker is the outermost layer and the only one that may log. The
    # application layer is forbidden it by its own guard -- a use case reports by
    # returning a value -- so this is where a swallowed fault becomes visible.
    "logging",
    "typing",
}

#: ``pydantic`` so a worker can validate an envelope against the domain record
#: it claims to be, rather than trusting fields one at a time.
ALLOWED_THIRD_PARTY = {"pydantic"}

#: Time and identifiers arrive through ports, and a rule is never decided here,
#: so a worker that reached for these would be doing someone else's job.
FORBIDDEN_MODULES = {"random", "uuid", "time", "os", "sys", "socket", "boto3", "botocore"}


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_there_are_modules_to_check() -> None:
    assert len(MODULES) >= 2, "this guard would pass vacuously with no modules"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_worker_imports_a_sibling_transport(path: pathlib.Path) -> None:
    for module in _imported_modules(_parse(path)):
        offending = [name for name in FORBIDDEN_PACKAGES if module.startswith(name)]
        assert not offending, (
            f"{path.name} imports {module}; {offending[0]} is a sibling transport, "
            "not a library, and sharing its shapes couples two contracts together"
        )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_worker_reaches_for_a_clock_a_random_source_or_an_sdk(
    path: pathlib.Path,
) -> None:
    """A worker that built its own client would bypass the composition root.

    Every worker's ``lambda_handler`` imports the composition root inside the
    function, so the SDK stays out of this package's module surface entirely.
    """
    offending = _imported_roots(_parse(path)) & FORBIDDEN_MODULES
    assert not offending, f"{path.name} imports {sorted(offending)}"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_worker_imports_outside_the_allowlist(path: pathlib.Path) -> None:
    unexpected = _imported_roots(_parse(path)) - ALLOWED_STDLIB - ALLOWED_THIRD_PARTY - {"services"}
    assert not unexpected, f"{path.name} imports {sorted(unexpected)}; add it deliberately"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_every_module_carries_a_docstring(path: pathlib.Path) -> None:
    if path.name == "__init__.py":
        return
    assert ast.get_docstring(_parse(path)), f"{path.name} has no module docstring"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_worker_decides_a_job_transition(path: pathlib.Path) -> None:
    """``services/domain/jobs.py`` is the only place a transition is decided.

    A worker calling ``start``, ``fail`` or ``retry`` directly would be deciding
    one here, outside the layer the tests describe. The controller calls them;
    a worker calls the controller.
    """
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ImportFrom) and node.module == "services.domain.jobs":
            imported = {alias.name for alias in node.names}
            deciding = imported & {"start", "succeed", "fail", "retry", "resolve_delivery"}
            assert not deciding, (
                f"{path.name} imports {sorted(deciding)} from the domain; a job "
                "transition is the controller's to ask for, not a worker's"
            )


def test_the_guard_would_notice_a_sibling_import() -> None:
    """The guards above pass today; this proves they are capable of failing."""
    offending = _imported_modules(ast.parse("from services.api.http import ok\n"))
    assert any(module.startswith(name) for module in offending for name in FORBIDDEN_PACKAGES)


def test_the_transition_guard_would_notice_a_direct_call() -> None:
    tree = ast.parse("from services.domain.jobs import fail\n")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "services.domain.jobs":
            assert {alias.name for alias in node.names} & {"fail"}
            return
    raise AssertionError("the guard's own shape has drifted")
