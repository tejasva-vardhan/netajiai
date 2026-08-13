from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from backend.app.application.evidence import EvidenceAsset
from backend.app.application.voice_drafts import SpeechToTextUnavailable
from backend.app.infrastructure.speech import DeepgramSpeechToText


class FakeObjectStore:
    def read_bytes(self, object_key: str) -> bytes:
        assert object_key == "evidence/audio.webm"
        return b"audio-bytes"


def _asset() -> EvidenceAsset:
    return EvidenceAsset(
        evidence_asset_id=uuid4(),
        citizen_id="oidc:citizen-1",
        asset_type="audio",
        content_type="audio/webm",
        byte_size=11,
        client_sha256="a" * 64,
        object_key="evidence/audio.webm",
        status="verified",
        capture_source="native_microphone",
        device_captured_at=datetime.now(timezone.utc),
        location_sample_id=None,
    )


def test_deepgram_transcribes_verified_audio_and_detects_hinglish_language():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Token deepgram-key"
        assert request.headers["content-type"] == "audio/webm"
        assert request.url.params["model"] == "nova-3"
        assert request.url.params["detect_language"] == "true"
        assert request.content == b"audio-bytes"
        return httpx.Response(
            200,
            json={
                "results": {
                    "channels": [
                        {
                            "detected_language": "hi",
                            "alternatives": [{"transcript": "Sadak mein gaddha hai", "confidence": 0.91}],
                        }
                    ]
                }
            },
        )

    adapter = DeepgramSpeechToText(
        api_key="deepgram-key",
        model="nova-3",
        object_store=FakeObjectStore(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.transcribe(_asset(), requested_language="hinglish")

    assert result.text == "Sadak mein gaddha hai"
    assert result.language == "hi"
    assert result.confidence == 0.91
    assert result.provider == "deepgram"
    assert result.model == "nova-3"


def test_deepgram_fails_closed_for_provider_errors():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(401))
    )
    adapter = DeepgramSpeechToText(
        api_key="deepgram-key",
        model="nova-3",
        object_store=FakeObjectStore(),
        client=client,
    )

    with pytest.raises(SpeechToTextUnavailable, match="temporarily unavailable"):
        adapter.transcribe(_asset(), requested_language="hi-IN")
