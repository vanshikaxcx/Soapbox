"""Merchant port. Adapters implement this; application code depends only on it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .models import FeeAssessment, ItemQuery, Line, Location, MerchantError, Observation


class Merchant(ABC):
    name: str

    @abstractmethod
    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[Observation] | MerchantError:
        """Return matching observations for one item, or a typed error."""

    @abstractmethod
    def refresh(
        self, location: Location, sku: str, deadline: datetime
    ) -> Observation | MerchantError:
        """Re-fetch a single SKU's current price/stock."""

    @abstractmethod
    def assess_fees(
        self, location: Location, exact_lines: list[Line], deadline: datetime
    ) -> FeeAssessment | None:
        """Return basket-level fees for the given lines, or None if unknown."""
