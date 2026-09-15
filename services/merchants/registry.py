"""Merchant registry. Single place that maps a merchant name to its connector."""
from __future__ import annotations

from .base import Merchant
from .blinkit import BlinkitMerchant
from .evidence import EvidenceSink, LocalDiskEvidenceSink
from .fixture import FixtureMerchant
from .models import Mode
from .zepto import ZeptoMerchant

LIVE_MERCHANT_NAMES = ("blinkit", "zepto")


def build_live_registry(evidence_sink: EvidenceSink | None = None) -> dict[str, Merchant]:
    sink = evidence_sink or LocalDiskEvidenceSink()
    return {
        "blinkit": BlinkitMerchant(sink),
        "zepto": ZeptoMerchant(sink),
    }


def build_fixture_registry() -> dict[str, Merchant]:
    return {name: FixtureMerchant(name) for name in LIVE_MERCHANT_NAMES}


def build_registry(mode: Mode) -> dict[str, Merchant]:
    """Callers must never mix results from a live and a fixture registry in one response."""
    if mode == Mode.LIVE:
        return build_live_registry()
    return build_fixture_registry()
