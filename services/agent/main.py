"""Agent container entrypoint: FastAPI + Strands + Playwright (SPEC section 3/5).

Called only by workflow task Lambdas via a rotated server-only token, never
directly by the browser.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from services.agent.config import AGENT_SERVICE_TOKEN
from services.agent.tools.search_merchants import search_merchants

app = FastAPI(title="proofpath-agent")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


class SearchRequest(BaseModel):
    location: dict
    item: dict
    mode: str = "live"


def _require_auth(authorization: str | None) -> None:
    if not AGENT_SERVICE_TOKEN:
        return  # local dev only; production config must set the token
    if authorization != f"Bearer {AGENT_SERVICE_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid agent service token")


@app.post("/tasks/search")
def run_search(req: SearchRequest, authorization: str | None = Header(default=None)) -> dict:
    """Thin HTTP wrapper around the allowlisted search_merchants tool.

    This is the deterministic path used directly by tests and by the workflow
    task Lambda. Strands model-driven calls go through the same tool function.
    """
    _require_auth(authorization)
    observations = search_merchants(req.location, req.item, req.mode)
    return {"observations": observations}
