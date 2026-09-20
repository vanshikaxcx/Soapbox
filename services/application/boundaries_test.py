"""Dependency-direction guards for the application layer (WP-08).

The domain had these from the start; the layer that assembles money-moving
transactions did not, which was an odd place for the gap. Application may depend
on the domain and on the standard library, and on nothing else: the moment it
imports boto3 directly, the ports stop being a seam and P4's adapters stop being
swappable.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).parent
MODULES = sorted(p for p in PACKAGE.glob("*.py") if not p.name.endswith("_test.py"))

ALLOWED_STDLIB = {
    "__future__",
    "abc",
    "collections",
    "copy",
    "dataclasses",
    "datetime",
    "enum",
    "functools",
    "typing",
    # The callback contract computes HMAC-SHA256 itself rather than reaching for
    # a crypto library: the signing input is part of the contract with P4.
    "hashlib",
    "hmac",
}
ALLOWED_THIRD_PARTY = {"pydantic"}

FORBIDDEN = {
    "boto3",
    "botocore",
    "aws_lambda_powertools",
    "fastapi",
    "starlette",
    "playwright",
    "requests",
    "httpx",
    "aiohttp",
    "sqlalchemy",
    "redis",
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


def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_there_are_modules_to_check() -> None:
    assert len(MODULES) >= 3, "this guard would pass vacuously with no modules"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_imports_infrastructure(path: pathlib.Path) -> None:
    offending = _imported_roots(_parse(path)) & FORBIDDEN
    assert not offending, (
        f"{path.name} imports {sorted(offending)}; infrastructure belongs behind a "
        "port so P4's adapters stay swappable"
    )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_imports_outside_the_allowlist(path: pathlib.Path) -> None:
    unexpected = _imported_roots(_parse(path)) - ALLOWED_STDLIB - ALLOWED_THIRD_PARTY - {"services"}
    assert not unexpected, f"{path.name} imports {sorted(unexpected)}; add it deliberately"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_application_depends_only_on_domain_and_itself(path: pathlib.Path) -> None:
    """Never on api, workers, adapters or the simulator -- those depend on us."""
    for node in ast.walk(_parse(path)):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(a.name for a in node.names if a.name.startswith("services."))
        for module in modules:
            if not module.startswith("services."):
                continue
            allowed = module.startswith(("services.domain", "services.application"))
            assert allowed, f"{path.name} imports {module}; that package depends on us"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_reaches_for_a_clock_or_randomness(path: pathlib.Path) -> None:
    """Time and identifiers arrive through the Clock and IdFactory ports.

    The fakes module is exempt: a test clock is precisely a thing that holds
    time, and it holds a value a test supplies rather than reading the system.
    """
    roots = _imported_roots(_parse(path))
    impure = roots & {"random", "uuid", "time", "os", "sys", "socket", "logging"}
    assert not impure, f"{path.name} imports {sorted(impure)}"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_every_module_carries_a_docstring(path: pathlib.Path) -> None:
    if path.name == "__init__.py":
        return
    assert ast.get_docstring(_parse(path)), f"{path.name} has no module docstring"
