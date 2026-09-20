"""Unit tests for the S3 evidence sink adapter (WP-01, AC-01-04).

No real AWS call is made: ``FakeS3Client`` is a hand-written double. Also
covers ``build_evidence_sink``'s composition-root selection, since a wrong
choice there would silently send deployed-environment evidence to local
disk inside an ephemeral Fargate task instead of S3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.merchants.evidence import LocalDiskEvidenceSink, S3EvidenceSink, build_evidence_sink

BUCKET = "proofpath-checkpoint-evidence"


class FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> object:
        self.put_calls.append(
            {"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType}
        )
        return {}


def test_save_uploads_to_the_configured_bucket_and_returns_the_key() -> None:
    client = FakeS3Client()
    sink = S3EvidenceSink(BUCKET, client=client)

    key = sink.save("blinkit", b"\x89PNG...", "image/png")

    assert len(client.put_calls) == 1
    call = client.put_calls[0]
    assert call["Bucket"] == BUCKET
    assert call["Key"] == key
    assert call["Key"].startswith("blinkit/")
    assert call["Key"].endswith(".png")
    assert call["Body"] == b"\x89PNG..."
    assert call["ContentType"] == "image/png"


def test_save_uses_a_bin_extension_for_a_non_png_content_type() -> None:
    client = FakeS3Client()
    sink = S3EvidenceSink(BUCKET, client=client)

    key = sink.save("zepto", b"raw-bytes", "application/octet-stream")

    assert key.endswith(".bin")


def test_build_evidence_sink_chooses_s3_when_the_bucket_env_var_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROOFPATH_EVIDENCE_BUCKET", BUCKET)

    sink = build_evidence_sink()

    assert isinstance(sink, S3EvidenceSink)
    assert sink.bucket == BUCKET


def test_build_evidence_sink_falls_back_to_local_disk_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PROOFPATH_EVIDENCE_BUCKET", raising=False)
    monkeypatch.chdir(tmp_path)  # LocalDiskEvidenceSink creates "./.evidence" on init

    sink = build_evidence_sink()

    assert isinstance(sink, LocalDiskEvidenceSink)
