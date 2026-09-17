"""Extraction port. Backends implement this; the agent depends only on it.

Mirrors `services.merchants.base.Merchant`: one abstract contract, one file
per backend, and a registry that picks a backend by `Mode` -- never a
runtime branch inside orchestration code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .models import ExtractionResult


class ExtractorUnavailable(Exception):
    """The backend cannot serve this request at all.

    Raised, never returned -- unlike a domain `DomainError`, this is not a
    per-item outcome the caller reasons about; it is "this whole call could
    not run" (no model configured, the model call itself failed, or the
    model's output could not be parsed). `services.agent.extract` catches
    this once per request and reports it as a single honest
    `unresolved` entry (`reason_code="extraction_unavailable"`), never a
    failed request.
    """


class Extractor(ABC):
    name: str

    @abstractmethod
    def extract_from_text(self, transcript: str, deadline: datetime) -> ExtractionResult:
        """Turn a raw transcript string into candidate items."""

    @abstractmethod
    def extract_from_image(
        self, image_bytes: bytes, mime_type: str, deadline: datetime
    ) -> ExtractionResult:
        """Turn a raw image (already decoded from base64) into candidate items."""


__all__ = ["Extractor", "ExtractorUnavailable"]
