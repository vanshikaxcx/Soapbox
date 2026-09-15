"""Shared typed contracts for merchant connectors (SPEC section 6)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Mode(str, Enum):
    LIVE = "live"
    FIXTURE = "fixture"


class ExtractionStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    NOT_FOUND = "not_found"
    ERROR = "error"


class Location(BaseModel):
    locality: str
    pincode: str
    address_hint: str | None = None


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


class MerchantErrorCode(str, Enum):
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
