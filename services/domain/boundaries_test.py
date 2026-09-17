"""Dependency-direction guards (WP-02 acceptance criteria 1, 14, 15).

These walk the AST of every module in the package rather than trusting a
convention. A reviewer can miss an added import; this cannot.
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
    "ast",
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fractions",
    "functools",
    "hashlib",
    "inspect",
    "itertools",
    "json",
    "pathlib",
    "re",
    "typing",
    "unicodedata",
}

ALLOWED_THIRD_PARTY = {"pydantic"}

#: Named explicitly so the failure message says what went wrong, not just "not allowed".
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
    "django",
    "flask",
}

#: Domain functions receive `now` as a parameter and IDs from their caller. A
#: clock, a random source or a logger inside this package would make its output
#: depend on something other than its inputs.
FORBIDDEN_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("time", "time"),
    ("uuid", "uuid4"),
    ("random", "random"),
}

FORBIDDEN_MODULES_FOR_PURITY = {"logging", "random", "uuid", "os", "sys", "socket", "time"}


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


def test_the_package_has_modules_to_check() -> None:
    assert len(MODULES) >= 8, "boundary test would vacuously pass with no modules"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_imports_infrastructure(path: pathlib.Path) -> None:
    roots = _imported_roots(_parse(path))
    offending = roots & FORBIDDEN
    assert not offending, f"{path.name} imports infrastructure: {sorted(offending)}"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_imports_anything_outside_the_allowlist(path: pathlib.Path) -> None:
    roots = _imported_roots(_parse(path))
    unexpected = roots - ALLOWED_STDLIB - ALLOWED_THIRD_PARTY - {"services"}
    assert not unexpected, (
        f"{path.name} imports {sorted(unexpected)}; add it to the allowlist "
        "deliberately or remove it"
    )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_imports_a_sibling_service(path: pathlib.Path) -> None:
    """services.domain may import itself and nothing else under services."""
    tree = _parse(path)
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            module = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("services."):
                    module = alias.name
        if module and module.startswith("services.") and not module.startswith(
            "services.domain"
        ):
            pytest.fail(f"{path.name} imports {module}; domain sits below every other package")


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_reaches_for_a_clock_randomness_or_a_logger(path: pathlib.Path) -> None:
    roots = _imported_roots(_parse(path))
    impure = roots & FORBIDDEN_MODULES_FOR_PURITY
    assert not impure, (
        f"{path.name} imports {sorted(impure)}; domain functions take `now` and IDs "
        "as arguments so their output depends only on their inputs"
    )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_module_calls_a_clock_or_random_source(path: pathlib.Path) -> None:
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value = node.func.value
            if isinstance(value, ast.Name):
                pair = (value.id, node.func.attr)
                assert pair not in FORBIDDEN_CALLS, f"{path.name} calls {pair[0]}.{pair[1]}()"


def test_every_module_carries_a_docstring() -> None:
    """A rule nobody can find is a rule nobody follows."""
    for path in MODULES:
        if path.name == "__init__.py":
            continue
        assert ast.get_docstring(_parse(path)), f"{path.name} has no module docstring"
