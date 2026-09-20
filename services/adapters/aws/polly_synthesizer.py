"""Real Polly adapter for SpeechSynthesizer (WP-05-A1).

Returns the actual synthesized audio bytes, unlike WP-01's AC-01-02
liveness-only adapter (which read the same ``AudioStream`` and reported only
its length -- correct for proving Bedrock/Polly/Transcribe are reachable,
useless for producing something a shopper can actually hear).
"""

from __future__ import annotations

from typing import Any, Protocol

from botocore.exceptions import ClientError

from services.application.ports.speech import SpeechSynthesisError, SpeechSynthesisResult


class PollyClient(Protocol):
    """The minimal boto3 Polly client surface this adapter depends on."""

    def synthesize_speech(self, **kwargs: Any) -> dict[str, Any]: ...


class PollySynthesizerAdapter:
    """Structurally satisfies ``SpeechSynthesizer``; see that module's docstring."""

    def __init__(self, client: PollyClient, *, voice_id: str, engine: str) -> None:
        self._client = client
        self._voice_id = voice_id
        self._engine = engine

    def synthesize(self, *, text: str) -> SpeechSynthesisResult | SpeechSynthesisError:
        try:
            response = self._client.synthesize_speech(
                Text=text,
                OutputFormat="mp3",
                VoiceId=self._voice_id,
                Engine=self._engine,
            )
        except ClientError as error:
            return SpeechSynthesisError(
                error_code=error.response["Error"]["Code"],
                message=error.response["Error"].get("Message", ""),
            )

        return SpeechSynthesisResult(
            audio_bytes=response["AudioStream"].read(),
            content_type=response["ContentType"],
        )


__all__ = ["PollyClient", "PollySynthesizerAdapter"]
