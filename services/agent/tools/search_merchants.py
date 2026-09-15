"""Allowlisted Strands tool: the model may only call this, never Playwright directly.

Agents propose; this tool performs the deterministic search and returns typed,
schema-constrained results. It never authorizes payment or approval actions.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.agent.config import ITEM_FETCH_DEADLINE_SECONDS
from services.merchants.models import ItemQuery, Location, Mode, Observation
from services.merchants.registry import build_registry


def search_merchants(
    location: dict, item: dict, mode: str = "live"
) -> list[dict]:
    """Search all registered merchants for one item.

    Args:
        location: {"locality": str, "pincode": str}
        item: {"name": str, "quantity": float, "unit": str}
        mode: "live" or "fixture" - never mixed in one response.

    Returns:
        List of Observation dicts, each tagged with its mode.
    """
    loc = Location(**location)
    query = ItemQuery(**item)
    registry = build_registry(Mode(mode))

    deadline = datetime.now(UTC) + timedelta(seconds=ITEM_FETCH_DEADLINE_SECONDS)

    results: list[Observation] = []
    for merchant in registry.values():
        outcome = merchant.search(loc, query, deadline)
        if isinstance(outcome, list):
            results.extend(outcome)
        # Typed MerchantError is dropped here; the caller (search workflow,
        # owned by P2/P3 jointly) is responsible for surfacing partial-result
        # coverage rather than failing the whole search.

    return [obs.model_dump(mode="json") for obs in results]
