"""Deterministic fixture connector for CI and demo fallback.

Fixture observations always carry mode=FIXTURE and must never be ranked or
displayed alongside live observations (SPEC honesty rules).
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from .base import Merchant
from .models import (
    ExtractionStatus,
    FeeAssessment,
    ItemQuery,
    Line,
    Location,
    MerchantError,
    Mode,
    Observation,
)

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class FixtureMerchant(Merchant):
    def __init__(self, merchant_name: str) -> None:
        self.name = merchant_name
        with open(os.path.join(_FIXTURE_DIR, f"{merchant_name}_fixture.json")) as f:
            self._catalog = json.load(f)

    def search(
        self, location: Location, item: ItemQuery, deadline: datetime
    ) -> list[Observation] | MerchantError:
        matches = [row for row in self._catalog if item.name.lower() in row["product_name"].lower()]
        return [
            Observation(
                merchant=self.name,
                sku=row["sku"],
                url=row["url"],
                product_name=row["product_name"],
                pack_size=row["pack_size"],
                unit=row["unit"],
                price_paise=row["price_paise"],
                in_stock=row["in_stock"],
                verified_location=location,
                fetch_time=datetime.now(UTC),
                evidence_key=f"fixture:{self.name}:{row['sku']}",
                extraction_status=ExtractionStatus.OK,
                mode=Mode.FIXTURE,
            )
            for row in matches
        ]

    def refresh(self, location: Location, sku: str, deadline: datetime) -> Observation:
        row = next(r for r in self._catalog if r["sku"] == sku)
        return Observation(
            merchant=self.name,
            sku=row["sku"],
            url=row["url"],
            product_name=row["product_name"],
            pack_size=row["pack_size"],
            unit=row["unit"],
            price_paise=row["price_paise"],
            in_stock=row["in_stock"],
            verified_location=location,
            fetch_time=datetime.now(UTC),
            evidence_key=f"fixture:{self.name}:{row['sku']}",
            extraction_status=ExtractionStatus.OK,
            mode=Mode.FIXTURE,
        )

    def assess_fees(
        self, location: Location, exact_lines: list[Line], deadline: datetime
    ) -> FeeAssessment | None:
        subtotal = sum(line.price_paise * int(line.quantity) for line in exact_lines)
        return FeeAssessment(
            merchant=self.name,
            location=location,
            line_hash="fixture",
            subtotal_paise=subtotal,
            delivery_fee_paise=2500,
            platform_fee_paise=500,
            other_fees_paise=0,
            completeness="complete",
            fetch_time=datetime.now(UTC),
        )
