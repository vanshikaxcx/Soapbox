"""GET /health — the one route WP-00 commits to. Unauthenticated, no AWS calls."""
from __future__ import annotations

from datetime import UTC, datetime

from services.api.envelope import success


def get_health() -> dict:
    return success({"status": "ok", "time": datetime.now(UTC).isoformat()})


def lambda_handler(event: dict, context: object) -> dict:
    """API Gateway proxy-integration entry point. Real routing added in WP-03/07."""
    import json

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(get_health()),
    }
