"""The search record (WP-02).

A search binds to an intent **revision**, not just an intent. That is what makes
an old search unable to become current again: accept a repair, the revision
advances, and every search taken against the old one is permanently stale.

``mode`` is on the search itself rather than on individual observations, because
a result set is entirely live or entirely fixture. Mixing them is the one thing
the honesty rules forbid outright, so the record makes a mixed set impossible to
represent rather than merely discouraged.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from services.domain.catalog import Observation
from services.domain.ids import Id, Mode, Timestamped


class SearchStatus(StrEnum):
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


class MerchantProgress(Timestamped):
    """How one merchant went. A failure here is reported, never hidden."""

    merchant_id: str = Field(min_length=1, max_length=64)
    items_requested: int = Field(ge=0)
    items_returned: int = Field(ge=0)
    error_code: str | None = None
    completed_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None and self.error_code is None


class Search(Timestamped):
    """One comparison run, bound to the intent revision it was taken against."""

    search_id: Id
    owner_id: Id
    intent_id: Id
    intent_revision: int = Field(ge=1)
    location: str = Field(min_length=1, max_length=200)
    mode: Mode
    status: SearchStatus = SearchStatus.RUNNING
    observations: tuple[Observation, ...] = ()
    progress: tuple[MerchantProgress, ...] = ()
    started_at: datetime
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _one_mode_for_the_whole_result_set(self) -> Search:
        """Live and fixture observations can never share a search.

        SPEC section 1: a result set is entirely one or entirely the other, and
        fixtures do not satisfy the two-live-merchant gate. Enforcing it here
        means no caller can assemble a mixed set by accident.
        """
        for observation in self.observations:
            if observation.mode is not self.mode:
                raise ValueError(
                    f"observation {observation.observation_id} is {observation.mode} "
                    f"but this search is {self.mode}; result sets are never mixed"
                )
        return self

    @property
    def merchants_covered(self) -> int:
        return sum(1 for entry in self.progress if entry.is_complete)

    @property
    def has_partial_coverage(self) -> bool:
        """One merchant failing yields partial results, never a failed search."""
        return any(entry.error_code is not None for entry in self.progress)


def is_current(search: Search, intent_revision: int) -> bool:
    """False once a repair has been accepted. Permanently."""
    return search.intent_revision == intent_revision


__all__ = [
    "MerchantProgress",
    "Search",
    "SearchStatus",
    "is_current",
]
