"""Speech ports for real voice sessions and turn playback (WP-05-A1).

Deliberately narrower than WP-01's original AC-01-02 liveness-check ports
(``bedrock_model``/``transcribe_streaming`` there proved AWS reachability by
discarding the actual transcript/audio payload -- correct for a one-shot
liveness proof, useless for a real feature). These two match the product
spec's actual architecture instead:

- Transcribe: the browser speaks directly to AWS over a presigned WSS URL
  (see docs/PROOFPATH-SPEC.md section 4's "Browser <-> Transcribe" row).
  This backend only ever issues that URL; it never relays audio itself, so
  there is no streaming client dependency here at all -- issuing a presigned
  URL is the same SigV4 query-signing primitive S3 presigned URLs use.
- Polly: synthesis happens server-side (the browser cannot hold Polly
  credentials), so this port returns the actual audio bytes to store, not a
  byte count.
"""

from __future__ import annotations

from typing import Protocol

from services.domain.ids import Record


class TranscribeSessionUrl(Record):
    url: str
    expires_in_seconds: int


class TranscribeUrlSigner(Protocol):
    def presign(
        self, *, language_code: str, media_sample_rate_hz: int, expires_in_seconds: int
    ) -> TranscribeSessionUrl:
        """A one-time, time-limited WSS URL. Never reused across sessions."""


class SpeechSynthesisResult(Record):
    audio_bytes: bytes
    content_type: str


class SpeechSynthesisError(Record):
    error_code: str
    message: str


class SpeechSynthesizer(Protocol):
    def synthesize(self, *, text: str) -> SpeechSynthesisResult | SpeechSynthesisError:
        """Synthesize once with the pinned voice/engine."""


class AudioSink(Protocol):
    def save(self, turn_id: str, content: bytes, content_type: str) -> str:
        """Persist synthesized audio and return an opaque audio_key."""

    def playback_url(self, audio_key: str, expires_in_seconds: int) -> str:
        """A time-limited URL a browser can play directly."""


__all__ = [
    "AudioSink",
    "SpeechSynthesisError",
    "SpeechSynthesisResult",
    "SpeechSynthesizer",
    "TranscribeSessionUrl",
    "TranscribeUrlSigner",
]
