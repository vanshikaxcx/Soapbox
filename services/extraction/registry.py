"""Extraction backend registry. Single place that maps a mode to a backend."""

from __future__ import annotations

from services.merchants.models import Mode

from .base import Extractor
from .bedrock import BedrockExtractor
from .fake import FakeExtractor


def build_extractor(mode: Mode) -> Extractor:
    """Callers must never mix a live-model result with a fixture one."""
    if mode == Mode.LIVE:
        return BedrockExtractor()
    return FakeExtractor()


__all__ = ["build_extractor"]
