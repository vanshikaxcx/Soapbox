"""PollySynthesizerAdapter (WP-05-A1). No real AWS calls."""

from __future__ import annotations

import io
from typing import Any

from botocore.exceptions import ClientError

from services.adapters.aws.polly_synthesizer import PollySynthesizerAdapter
from services.application.ports.speech import SpeechSynthesisError, SpeechSynthesisResult


class ScriptedPollyClient:
    def __init__(
        self, response: dict[str, Any] | None = None, error: ClientError | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def synthesize_speech(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def test_synthesize_returns_the_actual_audio_bytes_not_a_count() -> None:
    client = ScriptedPollyClient(
        response={
            "AudioStream": io.BytesIO(b"real-mp3-bytes"),
            "ContentType": "audio/mpeg",
            "ResponseMetadata": {"RequestId": "req-1"},
        }
    )
    adapter = PollySynthesizerAdapter(client, voice_id="Kajal", engine="neural")

    result = adapter.synthesize(text="Got it, five kilos of rice.")

    assert isinstance(result, SpeechSynthesisResult)
    assert result.audio_bytes == b"real-mp3-bytes"
    assert result.content_type == "audio/mpeg"


def test_synthesize_uses_the_pinned_voice_and_engine() -> None:
    client = ScriptedPollyClient(
        response={
            "AudioStream": io.BytesIO(b"x"),
            "ContentType": "audio/mpeg",
            "ResponseMetadata": {"RequestId": "req-1"},
        }
    )
    adapter = PollySynthesizerAdapter(client, voice_id="Kajal", engine="neural")

    adapter.synthesize(text="hello")

    assert client.calls[0]["VoiceId"] == "Kajal"
    assert client.calls[0]["Engine"] == "neural"
    assert client.calls[0]["Text"] == "hello"


def test_a_client_error_is_recorded_verbatim_not_raised() -> None:
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "SynthesizeSpeech"
    )
    adapter = PollySynthesizerAdapter(
        ScriptedPollyClient(error=error), voice_id="Kajal", engine="neural"
    )

    result = adapter.synthesize(text="hello")

    assert isinstance(result, SpeechSynthesisError)
    assert result.error_code == "ThrottlingException"
    assert result.message == "Rate exceeded"
