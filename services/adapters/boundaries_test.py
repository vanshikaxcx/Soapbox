"""Dependency-direction guards for the adapter layer (WP-07).

The domain and application packages each have one of these; adapters did not,
and adapters are the layer where the direction is easiest to get backwards. An
adapter exists to be *depended on*: the moment one imports ``services.api`` or
``services.workers`` to reuse something convenient, the composition root stops
being the only place a wiring decision is made, and the port stops being a seam.

This package is also the one place a cloud SDK is allowed, so the guard is the
mirror image of the other two: ``boto3`` is expected here, and forbidden
everywhere else by the guards that already exist.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).parent
MODULES = sorted(p for p in PACKAGE.glob("*.py") if not p.name.endswith("_test.py"))

#: Packages that depend on adapters, and therefore may never be imported by one.
DOWNSTREAM = (
    "services.api",
    "services.workers",
    "services.agent",
    "services.merchants",
    "services.simulator",
)

ALLOWED_STDLIB = {
    "__future__",
    "collections",
    "dataclasses",
    "enum",
    "functools",
    # The idempotency token on a transaction is a digest of that transaction.
    # Hashing is the adapter's own business here: the token exists because of
    # how *DynamoDB* retries, and nothing above this layer knows that.
    "hashlib",
    "importlib",
    # WP-05-A1's audio sink names each stored object with a random suffix, so
    # two uploads for one turn cannot collide. That name is the storage
    # adapter's own concern -- nothing above this layer knows an object key
    # exists -- so it belongs here rather than being passed down.
    "uuid",
    # The composition root is exactly, and only, where the environment is read.
    "os",
    "typing",
}

#: ``boto3``/``botocore`` are the point of this package. ``pydantic`` because a
#: record has to be serialised somewhere, and that somewhere is the adapter. The
#: ``mypy_boto3_*`` packages ship no runtime code at all -- they are imported
#: under ``TYPE_CHECKING`` so the SDK calls are actually checked rather than
#: silently typed ``Any``. Listed one by one, so adapting a new AWS service is a
#: deliberate line in this file rather than a wildcard nobody reads.
ALLOWED_THIRD_PARTY = {
    "boto3",
    "botocore",
    "mypy_boto3_dynamodb",
    "mypy_boto3_events",
    "mypy_boto3_stepfunctions",
    "pydantic",
}


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
    assert len(MODULES) >= 3, "this guard would pass vacuously with no modules"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_adapter_imports_a_package_that_depends_on_it(path: pathlib.Path) -> None:
    for module in _imported_modules(_parse(path)):
        offending = [name for name in DOWNSTREAM if module.startswith(name)]
        assert not offending, (
            f"{path.name} imports {module}; {offending[0]} depends on adapters, so "
            "importing it here inverts the direction and hides a wiring decision"
        )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_adapter_imports_outside_the_allowlist(path: pathlib.Path) -> None:
    unexpected = _imported_roots(_parse(path)) - ALLOWED_STDLIB - ALLOWED_THIRD_PARTY - {"services"}
    assert not unexpected, f"{path.name} imports {sorted(unexpected)}; add it deliberately"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_every_module_carries_a_docstring(path: pathlib.Path) -> None:
    if path.name == "__init__.py":
        return
    assert ast.get_docstring(_parse(path)), f"{path.name} has no module docstring"


def test_the_guard_would_notice_a_downstream_import() -> None:
    """The guards above pass today. This proves they would not pass on anything.

    A boundary test that has never failed is indistinguishable from one that
    cannot, so the check is run against a module that does the forbidden thing.
    """
    offending = ast.parse("from services.api.http import ok\n")
    modules = _imported_modules(offending)
    assert any(module.startswith(name) for module in modules for name in DOWNSTREAM)
