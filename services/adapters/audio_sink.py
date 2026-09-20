"""Audio storage port for synthesized turn playback (WP-05-A1).

Same dual local/S3 selection pattern as ``services/merchants/evidence.py``'s
``EvidenceSink``: local disk for dev/test, S3 (never chosen implicitly) for
the deployed environment. Playback additionally needs a presigned GET URL,
which evidence storage does not, since evidence is never served back to a
browser.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Protocol

from services.application.ports.speech import AudioSink


class S3Client(Protocol):
    """The minimal boto3 S3 client surface this adapter depends on."""

    def put_object(self, **kwargs: Any) -> Any: ...

    def generate_presigned_url(self, operation: str, **kwargs: Any) -> str: ...


class LocalDiskAudioSink:
    """Dev-only sink. Writes under ./.audio/. Never use in the deployed environment."""

    def __init__(self, root: str = ".audio") -> None:
        self.root = root
        os.makedirs(root, exist_ok=True)

    def save(self, turn_id: str, content: bytes, content_type: str) -> str:
        ext = "mp3" if content_type == "audio/mpeg" else "bin"
        key = f"{turn_id}/{uuid.uuid4().hex}.{ext}"
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return key

    def playback_url(self, audio_key: str, expires_in_seconds: int) -> str:
        # Local dev has no browser-reachable URL scheme for this; callers in
        # dev/test read the file directly via `root`/`audio_key` instead.
        return f"file://{os.path.join(self.root, audio_key)}"


class S3AudioSink:
    """Deployed-environment sink. Each object gets its own presigned GET URL."""

    def __init__(self, bucket: str, client: S3Client | None = None) -> None:
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._client = client

    def save(self, turn_id: str, content: bytes, content_type: str) -> str:
        ext = "mp3" if content_type == "audio/mpeg" else "bin"
        key = f"{turn_id}/{uuid.uuid4().hex}.{ext}"
        self._client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)
        return key

    def playback_url(self, audio_key: str, expires_in_seconds: int) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": audio_key},
            ExpiresIn=expires_in_seconds,
        )


def build_audio_sink() -> AudioSink:
    """Composition-root selection: S3 when `PROOFPATH_AUDIO_BUCKET` is set
    (the deployed environment), local disk otherwise. Never chosen implicitly
    inside a use case."""
    bucket = os.environ.get("PROOFPATH_AUDIO_BUCKET", "")
    if bucket:
        return S3AudioSink(bucket)
    return LocalDiskAudioSink()


__all__ = ["LocalDiskAudioSink", "S3AudioSink", "build_audio_sink"]
