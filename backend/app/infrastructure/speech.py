"""Speech-to-text adapter seams."""

from __future__ import annotations

from typing import Protocol

import httpx

from backend.app.application.evidence import EvidenceAsset
from backend.app.application.voice_drafts import (
    SpeechToText,
    SpeechToTextUnavailable,
    TranscriptionResult,
)


class MediaReader(Protocol):
    def read_bytes(self, object_key: str) -> bytes: ...


class UnconfiguredSpeechToText(SpeechToText):
    """Fail closed until an approved STT provider is injected."""

    def transcribe(
        self,
        asset: EvidenceAsset,
        *,
        requested_language: str | None,
    ) -> TranscriptionResult:
        del asset, requested_language
        raise SpeechToTextUnavailable("Speech-to-text adapter is not configured")


class FixtureSpeechToText(SpeechToText):
    """Deterministic test-only transcription adapter."""

    def __init__(
        self,
        *,
        text: str,
        language: str = "hi-IN",
        confidence: float = 0.96,
    ) -> None:
        self._text = text
        self._language = language
        self._confidence = confidence
        self.calls = 0

    def transcribe(
        self,
        asset: EvidenceAsset,
        *,
        requested_language: str | None,
    ) -> TranscriptionResult:
        if asset.asset_type != "audio" or asset.status != "verified":
            raise SpeechToTextUnavailable("Fixture requires verified audio")
        self.calls += 1
        return TranscriptionResult(
            text=self._text,
            language=requested_language or self._language,
            confidence=self._confidence,
            provider="fixture-stt-v1",
            model="fixture-hindi-en-v1",
        )


class DeepgramSpeechToText(SpeechToText):
    """Transcribe verified audio through Deepgram's prerecorded API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        object_store: MediaReader,
        endpoint: str = "https://api.deepgram.com/v1/listen",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Deepgram API key is required")
        if not model.strip():
            raise ValueError("Deepgram model is required")
        if timeout_seconds <= 0:
            raise ValueError("Deepgram timeout must be positive")
        self._api_key = api_key
        self._model = model
        self._object_store = object_store
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._client = client

    def transcribe(
        self,
        asset: EvidenceAsset,
        *,
        requested_language: str | None,
    ) -> TranscriptionResult:
        if asset.asset_type != "audio" or asset.status != "verified":
            raise SpeechToTextUnavailable("Deepgram requires verified audio")
        try:
            audio = self._object_store.read_bytes(asset.object_key)
            params: dict[str, str] = {
                "model": self._model,
                "smart_format": "true",
                "punctuate": "true",
            }
            if requested_language and requested_language != "hinglish":
                params["language"] = requested_language
            else:
                params["detect_language"] = "true"
            headers = {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": asset.content_type,
            }
            if self._client is None:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.post(
                        self._endpoint, params=params, headers=headers, content=audio
                    )
            else:
                response = self._client.post(
                    self._endpoint, params=params, headers=headers, content=audio
                )
            response.raise_for_status()
            payload = response.json()
            alternative = payload["results"]["channels"][0]["alternatives"][0]
            text = alternative.get("transcript")
            confidence = alternative.get("confidence")
            language = (
                payload.get("results", {}).get("channels", [{}])[0].get("detected_language")
                or requested_language
                or "und"
            )
            if not isinstance(text, str) or not isinstance(confidence, (int, float)):
                raise ValueError("Deepgram returned an invalid transcript")
            return TranscriptionResult(
                text=text,
                language=str(language),
                confidence=float(confidence),
                provider="deepgram",
                model=self._model,
            )
        except SpeechToTextUnavailable:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise SpeechToTextUnavailable(
                "Deepgram transcription is temporarily unavailable"
            ) from exc
