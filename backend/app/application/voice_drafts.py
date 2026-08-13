"""Voice-to-draft application flow with explicit speech-provider boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.app.application.drafts import ComplaintDraftService
from backend.app.application.evidence import EvidenceAsset, EvidenceMetadataRepository
from backend.app.contracts.ai import (
    ComplaintDraftRequest,
    VoiceDraftResponse,
)
from backend.app.contracts.identity import AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    provider: str
    model: str


class SpeechToText(Protocol):
    """Transcribe a server-owned verified audio asset."""

    def transcribe(
        self,
        asset: EvidenceAsset,
        *,
        requested_language: str | None,
    ) -> TranscriptionResult: ...


@dataclass(frozen=True, slots=True)
class StoredVoiceDraft:
    """A citizen-scoped request binding, never the generated draft payload."""

    request_fingerprint: str


class VoiceDraftRequestRepository(Protocol):
    """Persist only the request binding needed for idempotency checks."""

    def find(
        self, citizen_id: str, idempotency_key: str
    ) -> StoredVoiceDraft | None: ...

    def persist(
        self,
        *,
        citizen_id: str,
        audio_asset_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> StoredVoiceDraft: ...


class VoiceDraftRejected(ValueError):
    """The supplied audio cannot be used for a voice draft."""


class SpeechToTextUnavailable(RuntimeError):
    """No approved speech-to-text adapter is available."""


class VoiceDraftIdempotencyConflict(ValueError):
    """The same citizen/key was reused for a different voice-draft request."""


@dataclass(frozen=True, slots=True)
class VoiceDraftService:
    evidence_repository: EvidenceMetadataRepository
    request_repository: VoiceDraftRequestRepository
    speech_to_text: SpeechToText
    drafts: ComplaintDraftService

    def extract(
        self,
        principal: AuthenticatedPrincipal,
        *,
        audio_asset_id: UUID,
        language: str | None,
        idempotency_key: str,
        now: datetime,
    ) -> VoiceDraftResponse:
        if not principal.subject_ref.strip() or not principal.identity_verified:
            raise VoiceDraftRejected("Verified citizen identity is required")
        if not idempotency_key.strip():
            raise VoiceDraftIdempotencyConflict("Idempotency-Key is required")
        request_fingerprint = _request_fingerprint(audio_asset_id, language)
        existing = self.request_repository.find(principal.subject_ref, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise VoiceDraftIdempotencyConflict(
                    "Voice-draft idempotency key belongs to another request"
                )
            # The response contains the bounded read-back description, which is
            # derived from the transcript. Re-run the non-authoritative draft
            # flow instead of persisting that citizen text for replay.
        asset = self.evidence_repository.find_owned(
            principal.subject_ref, audio_asset_id
        )
        if asset is None:
            raise VoiceDraftRejected("Audio evidence was not found")
        if asset.asset_type != "audio" or asset.status != "verified":
            raise VoiceDraftRejected("Verified audio evidence is required")
        try:
            transcription = self.speech_to_text.transcribe(
                asset,
                requested_language=language,
            )
        except SpeechToTextUnavailable:
            raise
        except Exception as exc:
            raise SpeechToTextUnavailable(
                "Speech transcription is temporarily unavailable"
            ) from exc
        text = transcription.text.strip()
        if not text or len(text) > 10_000:
            raise VoiceDraftRejected("The voice note did not contain usable speech")
        if not 0 <= transcription.confidence <= 1:
            raise VoiceDraftRejected("Speech transcription confidence is invalid")
        if not transcription.language.strip():
            raise VoiceDraftRejected("Speech transcription language is missing")
        if not transcription.provider.strip() or not transcription.model.strip():
            raise VoiceDraftRejected("Speech transcription provenance is missing")
        draft = self.drafts.extract(
            principal,
            ComplaintDraftRequest(
                text=text,
                language=language or transcription.language,
            ),
        )
        response = VoiceDraftResponse(
            draft=draft,
            transcription_language=transcription.language,
            transcription_confidence=transcription.confidence,
            transcription_provider=transcription.provider,
            transcription_model=transcription.model,
        )
        stored = self.request_repository.persist(
            citizen_id=principal.subject_ref,
            audio_asset_id=audio_asset_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            now=now,
        )
        if stored.request_fingerprint != request_fingerprint:
            raise VoiceDraftIdempotencyConflict(
                "Voice-draft idempotency key belongs to another request"
            )
        return response


def _request_fingerprint(audio_asset_id: UUID, language: str | None) -> str:
    canonical = json.dumps(
        {"audio_asset_id": str(audio_asset_id), "language": language},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
