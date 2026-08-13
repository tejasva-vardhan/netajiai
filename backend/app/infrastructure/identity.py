"""Identity provider adapters.

The sandbox adapter is deterministic test/development infrastructure. It is
not a substitute for DigiLocker's Requester integration in production.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from backend.app.contracts.identity import IdentityVerificationResult


class SandboxDigiLockerVerifier:
    """Deterministic local verifier for contract tests and development."""

    def verify(self, consent_reference: str) -> IdentityVerificationResult:
        reference = consent_reference.strip()
        if not reference:
            raise ValueError("consent_reference is required")
        subject_digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        return IdentityVerificationResult(
            subject_ref=f"digilocker:sandbox:{subject_digest}",
            status="verified",
            provider="digilocker",
            method="sandbox",
            verified_claims={},
            consent_id=f"sandbox:{subject_digest}",
            verified_at=now,
        )


@dataclass(frozen=True, slots=True)
class RequesterVerificationPayload:
    subject_ref: str
    status: str
    consent_id: str
    verified_claims: dict[str, str]
    verified_at: datetime | None = None
    expires_at: datetime | None = None


class DigiLockerRequesterTransport(Protocol):
    """Transport supplied after Requester onboarding and API review."""

    def verify_consent(self, consent_reference: str) -> RequesterVerificationPayload: ...


class DigiLockerRequesterVerifier:
    """Policy adapter around the approved DigiLocker Requester transport.

    Endpoint URLs, credentials, OAuth scopes, and response parsing belong to
    the injected transport because API Setu supplies them during partner
    onboarding. Raw documents are never accepted by this boundary.
    """

    def __init__(
        self,
        transport: DigiLockerRequesterTransport,
        *,
        allowed_claim_keys: frozenset[str] = frozenset(),
    ) -> None:
        self._transport = transport
        self._allowed_claim_keys = allowed_claim_keys

    def verify(self, consent_reference: str) -> IdentityVerificationResult:
        reference = consent_reference.strip()
        if not reference:
            raise ValueError("consent_reference is required")
        payload = self._transport.verify_consent(reference)
        if payload.status not in {"verified", "pending", "rejected", "unavailable"}:
            raise ValueError("Requester returned an unsupported verification status")
        claims = {
            key: value
            for key, value in payload.verified_claims.items()
            if key in self._allowed_claim_keys
        }
        return IdentityVerificationResult(
            subject_ref=payload.subject_ref,
            status=payload.status,  # type: ignore[arg-type]
            provider="digilocker",
            method="requester_oauth",
            verified_claims=claims,
            consent_id=payload.consent_id,
            verified_at=payload.verified_at,
            expires_at=payload.expires_at,
        )
