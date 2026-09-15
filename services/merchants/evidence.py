"""Evidence sink port. Real implementation (S3) is supplied by P4; local dev uses disk."""
from __future__ import annotations

import os
import uuid
from typing import Protocol


class EvidenceSink(Protocol):
    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        """Persist evidence bytes and return an opaque evidence_key."""


class LocalDiskEvidenceSink:
    """Dev-only sink. Writes under ./.evidence/. Never use in the deployed environment."""

    def __init__(self, root: str = ".evidence") -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, merchant: str, content: bytes, content_type: str) -> str:
        ext = "png" if content_type == "image/png" else "bin"
        key = f"{merchant}/{uuid.uuid4().hex}.{ext}"
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return key
