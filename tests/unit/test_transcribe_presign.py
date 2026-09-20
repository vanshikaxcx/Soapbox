"""TranscribePresignAdapter (WP-05-A1). No real AWS calls -- credentials are
hand-written, never the real SDK's."""

from __future__ import annotations

from services.adapters.aws.transcribe_presign import TranscribePresignAdapter


class FakeFrozenCredentials:
    access_key: str = "AKIAFAKEFAKEFAKEFAKE"
    secret_key: str = "fake-secret"
    token: str | None = None


class FakeCredentialsProvider:
    def get_frozen_credentials(self) -> FakeFrozenCredentials:
        return FakeFrozenCredentials()


def test_presigned_url_is_wss_and_scoped_to_the_transcribe_service() -> None:
    adapter = TranscribePresignAdapter(credentials=FakeCredentialsProvider(), region="ap-south-1")
    result = adapter.presign(
        language_code="en-IN", media_sample_rate_hz=16_000, expires_in_seconds=60
    )

    assert result.url.startswith("wss://transcribestreaming.ap-south-1.amazonaws.com:8443/")
    assert "stream-transcription-websocket" in result.url
    assert "X-Amz-Signature=" in result.url
    assert result.expires_in_seconds == 60


def test_presigned_url_carries_the_requested_language_and_sample_rate() -> None:
    adapter = TranscribePresignAdapter(credentials=FakeCredentialsProvider(), region="ap-south-1")
    result = adapter.presign(
        language_code="hi-IN", media_sample_rate_hz=8_000, expires_in_seconds=60
    )

    assert "language-code=hi-IN" in result.url
    assert "sample-rate=8000" in result.url
    assert "media-encoding=pcm" in result.url
