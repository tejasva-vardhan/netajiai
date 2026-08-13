"""Capture attestation and media-inspection adapters."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from backend.app.application.evidence import (
    CaptureAttestation,
    EvidenceAsset,
    EvidenceProviderUnavailable,
    InspectionResult,
)


class UnconfiguredCaptureAttestationVerifier:
    def verify(
        self, token: str, asset_type: str, citizen_id: str, idempotency_key: str
    ) -> CaptureAttestation:
        del token, asset_type, citizen_id, idempotency_key
        raise EvidenceProviderUnavailable(
            "Capture attestation verifier is not configured"
        )


class FixtureCaptureAttestationVerifier:
    """Test-only attestation fixture with explicit native-capture semantics."""

    def verify(
        self, token: str, asset_type: str, citizen_id: str, idempotency_key: str
    ) -> CaptureAttestation:
        if not citizen_id.strip() or not idempotency_key.strip():
            raise ValueError("Authenticated citizen and idempotency key are required")
        if not token.startswith("fixture:native:"):
            raise ValueError("Unsupported capture attestation")
        source = "native_microphone" if asset_type == "audio" else "native_camera"
        return CaptureAttestation(
            capture_source=source,
            device_captured_at=datetime.now(timezone.utc),
            attestation_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )


class UnconfiguredMediaInspector:
    def inspect(self, stored_object: object, asset: EvidenceAsset) -> InspectionResult:
        del stored_object, asset
        raise EvidenceProviderUnavailable("Media inspector is not configured")


class MetadataInspectionFixture:
    """Test-only inspector; real malware/clarity/reuse checks remain required."""

    def inspect(self, stored_object: object, asset: EvidenceAsset) -> InspectionResult:
        del stored_object
        return InspectionResult(accepted=asset.capture_source.startswith("native_"))


class ReviewRequiredInspectionFixture:
    """Test-only signal fixture for the human-review branch."""

    def inspect(self, stored_object: object, asset: EvidenceAsset) -> InspectionResult:
        del stored_object, asset
        return InspectionResult(
            accepted=False,
            review_required=True,
            reason_codes=("clarity_uncertain",),
        )


class LocalCaptureAttestationVerifier:
    """Accept the explicit local mobile fixture and signed browser sessions."""

    def __init__(self, browser: Any) -> None:
        self._browser = browser
        self._fixture = FixtureCaptureAttestationVerifier()

    def verify(
        self, token: str, asset_type: str, citizen_id: str, idempotency_key: str
    ) -> CaptureAttestation:
        if token.startswith("v1."):
            return self._browser.verify(token, asset_type, citizen_id, idempotency_key)
        return self._fixture.verify(token, asset_type, citizen_id, idempotency_key)


class LocalMediaInspector:
    """Verify native fixtures and route browser captures to operator review."""

    def inspect(self, stored_object: object, asset: EvidenceAsset) -> InspectionResult:
        del stored_object
        if asset.capture_source.startswith("browser_"):
            return InspectionResult(
                accepted=False,
                review_required=True,
                reason_codes=("browser_capture_review",),
            )
        return InspectionResult(accepted=asset.capture_source.startswith("native_"))
