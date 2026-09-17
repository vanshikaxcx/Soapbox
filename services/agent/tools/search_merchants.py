"""Allowlisted Strands tool: the model may only call this, never Playwright directly.

Agents propose; this tool performs the deterministic search and returns typed,
schema-constrained results. It never authorizes payment or approval actions.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from services.agent.config import ITEM_FETCH_DEADLINE_SECONDS
from services.merchants.models import ItemQuery, Location, Mode, Observation
from services.merchants.registry import build_registry


def search_merchants(
    location: dict[str, Any], item: dict[str, Any], mode: str = "live"
) -> list[dict[str, Any]]:
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

    # Each merchant.search() call routes internally to its own connector's
    # browser-engine thread (see browser_pool.py) — Blinkit's chromium and
    # Zepto's lightpanda are independent, so running these calls concurrently
    # here actually overlaps them rather than just launching them at once.
    # Confirmed live: two-merchant wall time drops close to the slower
    # merchant alone rather than their sum.
    results: list[Observation] = []
    with ThreadPoolExecutor(max_workers=max(len(registry), 1)) as executor:
        futures = [
            executor.submit(merchant.search, loc, query, deadline)
            for merchant in registry.values()
        ]
        for future in futures:
            outcome = future.result()
            if isinstance(outcome, list):
                results.extend(outcome)
            # Typed MerchantError is dropped here; the caller (search
            # workflow, owned by P2/P3 jointly) is responsible for surfacing
            # partial-result coverage rather than failing the whole search.

    return [obs.model_dump(mode="json") for obs in results]
