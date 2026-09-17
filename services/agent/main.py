"""Agent container entrypoint: FastAPI + Strands + Playwright (SPEC section 3/5).

Called only by workflow task Lambdas via a rotated server-only token, never
directly by the browser.
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from services.agent.config import AGENT_SERVICE_TOKEN, TESTED_LOCALITY_PINCODE
from services.agent.tools.search_merchants import search_merchants
from services.merchants.blinkit import warm_location

app = FastAPI(title="proofpath-agent")


@app.on_event("startup")
def _warm_blinkit_location() -> None:
    """Pay Blinkit's ~8s location-selection cost at container boot, not on a
    live request. Runs in the background so /health responds immediately;
    a real request landing before this finishes blocks on the same
    per-pincode lock inside warm_location() rather than racing it — see
    blinkit.py's module docstring.
    """
    threading.Thread(
        target=warm_location, args=(TESTED_LOCALITY_PINCODE,), daemon=True
    ).start()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


class SearchRequest(BaseModel):
    location: dict[str, Any]
    item: dict[str, Any]
    mode: str = "live"


def _require_auth(authorization: str | None) -> None:
    if not AGENT_SERVICE_TOKEN:
        return  # local dev only; production config must set the token
    if authorization != f"Bearer {AGENT_SERVICE_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid agent service token")


@app.post("/tasks/search")
def run_search(
    req: SearchRequest, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    """Thin HTTP wrapper around the allowlisted search_merchants tool.

    This is the deterministic path used directly by tests and by the workflow
    task Lambda. Strands model-driven calls go through the same tool function.
    """
    _require_auth(authorization)
    observations = search_merchants(req.location, req.item, req.mode)
    return {"observations": observations}
