"""Local-only FastAPI wrapper around the Lambda handlers, for `make dev-api`.

Not deployed. Deployment uses API Gateway + Lambda directly (services/api/health.py
etc. as handlers), per SPEC section 3.
"""
from __future__ import annotations

from fastapi import FastAPI

from services.api.health import get_health

app = FastAPI(title="proofpath-api-local")


@app.get("/health")
def health() -> dict:
    return get_health()
