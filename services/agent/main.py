"""Agent container entrypoint: FastAPI + Strands + Playwright (SPEC section 3/5).

Called only by workflow task Lambdas via a rotated server-only token, never
directly by the browser.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from services.agent.compare import run_comparison
from services.agent.config import AGENT_SERVICE_TOKEN, TESTED_LOCALITY_PINCODE
from services.agent.tools.search_merchants import search_merchants
from services.application.ports import IdFactory
from services.domain.ids import Mode as DomainMode
from services.domain.intent import Intent
from services.merchants.blinkit import warm_location
from services.merchants.models import Location

app = FastAPI(title="proofpath-agent")


class UuidIdFactory:
    """Real `IdFactory`: a uuid4 hex always satisfies WP-02's `Id` pattern.

    Fine for the agent's own task-scoped identifiers (a comparison run's
    `search_id`/`basket_id`); persisted, durable identifiers belong to
    WP-07's store, not this container.
    """

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"


_id_factory: IdFactory = UuidIdFactory()


@app.on_event("startup")
def _warm_blinkit_location() -> None:
    """Pay Blinkit's ~8s location-selection cost at container boot, not on a
    live request. Runs in the background so /health responds immediately;
    a real request landing before this finishes blocks on the same
    per-pincode lock inside warm_location() rather than racing it — see
    blinkit.py's module docstring.
    """
    threading.Thread(target=warm_location, args=(TESTED_LOCALITY_PINCODE,), daemon=True).start()


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


class CompareRequest(BaseModel):
    #: The full domain `Intent` (owner_id, items, location, budget_paise, ...),
    #: as `Intent.model_dump(mode="json")` would produce it. WP-05 (voice/photo
    #: intent capture) is what builds one of these from a shopper's request;
    #: this endpoint takes it already built.
    intent: dict[str, Any]
    #: Structured search location -- distinct from `intent["location"]`
    #: (a display string): merchant connectors need locality/pincode.
    location: dict[str, Any]
    mode: str = "live"


@app.post("/tasks/compare")
def run_compare(
    req: CompareRequest, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    """Search every registered merchant for every item, then compare (WP-06).

    Thin HTTP wrapper around `run_comparison`, the same shape as `/tasks/search`
    above: deterministic, callable directly by tests and by the workflow task
    Lambda, and by Strands model-driven calls through the same path.
    """
    _require_auth(authorization)
    # `Record` (WP-02) is strict: a plain dict from a JSON body still has
    # Python lists/str where these models want tuples/enums, which strict
    # `model_validate` rejects outright. `model_validate_json` applies
    # pydantic's JSON-mode coercion, which is what a JSON request body is.
    intent = Intent.model_validate_json(json.dumps(req.intent))
    location = Location.model_validate(req.location)
    outcome = run_comparison(
        intent=intent,
        location=location,
        mode=DomainMode(req.mode),
        now=datetime.now(UTC),
        id_factory=_id_factory,
    )
    return outcome.model_dump(mode="json")
