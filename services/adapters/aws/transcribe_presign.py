"""Real adapter for TranscribeUrlSigner (WP-05-A1).

Issues a presigned WSS URL for AWS Transcribe's streaming endpoint using
SigV4 *query-string* signing -- the same primitive S3 presigned URLs use
(``botocore.auth.SigV4QueryAuth``), not header signing. The browser then
opens this URL directly and streams PCM audio to AWS itself; this backend
never touches the audio.
"""

from __future__ import annotations

from typing import Protocol

from services.application.ports.speech import TranscribeSessionUrl


class FrozenCredentials(Protocol):
    access_key: str
    secret_key: str
    token: str | None


class CredentialsProvider(Protocol):
    def get_frozen_credentials(self) -> FrozenCredentials: ...


class TranscribePresignAdapter:
    """Structurally satisfies ``TranscribeUrlSigner``; see that module's docstring."""

    def __init__(self, *, credentials: CredentialsProvider, region: str) -> None:
        self._credentials = credentials
        self._region = region

    def presign(
        self, *, language_code: str, media_sample_rate_hz: int, expires_in_seconds: int
    ) -> TranscribeSessionUrl:
        from botocore.auth import SigV4QueryAuth
        from botocore.awsrequest import AWSRequest

        host = f"transcribestreaming.{self._region}.amazonaws.com:8443"
        path = "/stream-transcription-websocket"
        params = {
            "language-code": language_code,
            "media-encoding": "pcm",
            "sample-rate": str(media_sample_rate_hz),
        }
        query = "&".join(f"{key}={value}" for key, value in params.items())
        request = AWSRequest(method="GET", url=f"https://{host}{path}?{query}")
        SigV4QueryAuth(
            self._credentials.get_frozen_credentials(),
            "transcribe",
            self._region,
            expires=expires_in_seconds,
        ).add_auth(request)

        prepared = request.prepare()
        # wss://, not https:// -- the same signed query string is valid for
        # either scheme; only the scheme the browser actually connects with
        # changes.
        url = "wss://" + prepared.url.removeprefix("https://")
        return TranscribeSessionUrl(url=url, expires_in_seconds=expires_in_seconds)


__all__ = ["CredentialsProvider", "FrozenCredentials", "TranscribePresignAdapter"]
