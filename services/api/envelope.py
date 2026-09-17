"""Shared response envelope helpers. Every handler uses these, never ad-hoc dicts.

Carried over from WP-00's first baseline, which the current baseline replaced
with the typed models in ``services/api/health.py``. Those models are
health-specific -- ``code`` is ``Literal["internal_error"]`` and ``status`` is
``Literal["ok"]`` -- so they cannot yet carry WP-02's 26 error codes. Generalising
them is P4's call; until then the purchase handlers use these, and the shapes
they emit are identical.
"""

from __future__ import annotations

import uuid
from typing import Any


def success(data: Any, request_id: str | None = None) -> dict[str, Any]:
    return {"data": data, "request_id": request_id or _new_request_id()}


def error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id or _new_request_id(),
    }


def _new_request_id() -> str:
    return uuid.uuid4().hex
