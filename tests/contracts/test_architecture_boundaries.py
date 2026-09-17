import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_DOMAIN_IMPORT_ROOTS = {
    "boto3",
    "botocore",
    "fastapi",
    "aws_lambda_powertools",
    "playwright",
    "react",
}


def test_domain_has_no_transport_or_concrete_adapter_imports() -> None:
    domain_root = REPOSITORY_ROOT / "services" / "domain"

    for source_path in domain_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not imported_roots & FORBIDDEN_DOMAIN_IMPORT_ROOTS
        assert "services.api" not in source_path.read_text(encoding="utf-8")
        assert "services.adapters" not in source_path.read_text(encoding="utf-8")
