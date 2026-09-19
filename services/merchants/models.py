"""Shared typed contracts for merchant connectors (SPEC section 6)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Mode(StrEnum):
    LIVE = "live"
    FIXTURE = "fixture"


class ExtractionStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    NOT_FOUND = "not_found"
    ERROR = "error"


class Location(BaseModel):
    locality: str
    pincode: str
    address_hint: str | None = None
    # Server-derived store/serviceability-zone id from the merchant's own
    # response to a committed location (e.g. Blinkit's dark-store id) --
    # never a UI-rendered echo of `pincode`/`locality`. `None` when a
    # connector hasn't extracted one (SPEC AC-01-04 needs this field to
    # differ across localities as ground-truth evidence of real
    # server-side location resolution).
    merchant_zone_id: str | None = None


class ItemQuery(BaseModel):
    name: str
    quantity: float
    unit: str
    hard_attributes: dict[str, str] = Field(default_factory=dict)
    flexibility: str = "strict"  # "strict" | "brand_flexible" | "pack_flexible"


class Observation(BaseModel):
    merchant: str
    sku: str
    url: str
    product_name: str
    pack_size: float
    unit: str
    price_paise: int
    in_stock: bool
    verified_location: Location
    fetch_time: datetime
    evidence_key: str
    extraction_status: ExtractionStatus
    mode: Mode


class Line(BaseModel):
    sku: str
    quantity: float
    price_paise: int


class FeeAssessment(BaseModel):
    merchant: str
    location: Location
    line_hash: str
    subtotal_paise: int
    delivery_fee_paise: int | None = None
    platform_fee_paise: int | None = None
    other_fees_paise: int | None = None
    completeness: str  # "complete" | "estimated" | "unknown"
    fetch_time: datetime


class MerchantErrorCode(StrEnum):
    TIMEOUT = "timeout"
    CAPTCHA = "captcha"
    BLOCKED = "blocked"
    LOCATION_UNSUPPORTED = "location_unsupported"
    NOT_FOUND = "not_found"
    LAYOUT_CHANGED = "layout_changed"
    UNKNOWN = "unknown"


class MerchantError(BaseModel):
    merchant: str
    code: MerchantErrorCode
    message: str
    occurred_at: datetime
