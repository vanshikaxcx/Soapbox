"""AudioSink adapters (WP-05-A1): local disk for dev, S3 for deployed.

Same shape of test as tests/unit/test_evidence_sink.py's EvidenceSink pair,
which this package's composition-root selection mirrors.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from services.adapters.audio_sink import LocalDiskAudioSink, S3AudioSink, build_audio_sink

BUCKET = "proofpath-audio-test"


def test_local_disk_sink_round_trips_bytes(tmp_path: Any) -> None:
    sink = LocalDiskAudioSink(root=str(tmp_path))
    key = sink.save("turn-0001", b"fake-mp3-bytes", "audio/mpeg")

    with open(os.path.join(str(tmp_path), key), "rb") as f:
        assert f.read() == b"fake-mp3-bytes"


def test_local_disk_sink_keys_are_namespaced_by_turn(tmp_path: Any) -> None:
    sink = LocalDiskAudioSink(root=str(tmp_path))
    key = sink.save("turn-0001", b"x", "audio/mpeg")
    assert key.startswith("turn-0001/")
    assert key.endswith(".mp3")


class ScriptedS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> Any:
        self.put_calls.append(kwargs)
        return {}

    def generate_presigned_url(self, operation: str, **kwargs: Any) -> str:
        return f"https://s3.example/{kwargs['Params']['Key']}?op={operation}&expires={kwargs['ExpiresIn']}"


def test_s3_sink_stores_the_exact_bytes_and_content_type() -> None:
    client = ScriptedS3Client()
    sink = S3AudioSink(BUCKET, client=client)

    key = sink.save("turn-0001", b"fake-mp3-bytes", "audio/mpeg")

    assert client.put_calls[0]["Bucket"] == BUCKET
    assert client.put_calls[0]["Key"] == key
    assert client.put_calls[0]["Body"] == b"fake-mp3-bytes"
    assert client.put_calls[0]["ContentType"] == "audio/mpeg"


def test_s3_sink_playback_url_is_presigned_and_time_limited() -> None:
    client = ScriptedS3Client()
    sink = S3AudioSink(BUCKET, client=client)
    key = sink.save("turn-0001", b"x", "audio/mpeg")

    url = sink.playback_url(key, expires_in_seconds=300)

    assert key in url
    assert "expires=300" in url


def test_build_audio_sink_chooses_s3_when_the_bucket_env_var_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROOFPATH_AUDIO_BUCKET", BUCKET)
    sink = build_audio_sink()
    assert isinstance(sink, S3AudioSink)
    assert sink.bucket == BUCKET


def test_build_audio_sink_chooses_local_disk_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROOFPATH_AUDIO_BUCKET", raising=False)
    sink = build_audio_sink()
    assert isinstance(sink, LocalDiskAudioSink)
