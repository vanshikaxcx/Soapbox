"""Shared response envelope helpers. Every handler uses these, never ad-hoc dicts."""
from __future__ import annotations

import uuid
from typing import Any


def success(data: Any, request_id: str | None = None) -> dict:
    return {"data": data, "request_id": request_id or _new_request_id()}


def error(
    code: str, message: str, details: dict | None = None, request_id: str | None = None
) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id or _new_request_id(),
    }


def _new_request_id() -> str:
    return uuid.uuid4().hex
