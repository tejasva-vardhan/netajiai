"""Evidence verification adapters and deterministic policy checks."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.complaints import (
    EvidenceVerificationRequest,
    EvidenceVerificationResult,
)
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import EvidenceAssetRecord


class AcceptedEvidenceFixture:
    """Test-only fixture; never wire this into a production app."""

    def verify(
        self,
        principal: AuthenticatedPrincipal,
        request: EvidenceVerificationRequest,
    ) -> EvidenceVerificationResult:
        del principal
        accepted = bool(request.evidence_asset_ids and request.citizen_confirmation)
        return EvidenceVerificationResult(
            accepted=accepted,
            reason="Evidence confirmation is incomplete" if not accepted else "",
        )


class SqlAlchemyEvidenceVerifier:
    """Verify only server-recorded, owned, fully inspected evidence assets."""

    _INFRASTRUCTURE_TYPES = frozenset(
        {"pothole", "water", "drainage", "road", "streetlight", "garbage"}
    )

    def __init__(self, session: Session) -> None:
        self._session = session

    def verify(
        self,
        principal: AuthenticatedPrincipal,
        request: EvidenceVerificationRequest,
    ) -> EvidenceVerificationResult:
        if not request.citizen_confirmation:
            return EvidenceVerificationResult(False, "Citizen confirmation is required")
        if not request.evidence_asset_ids:
            return EvidenceVerificationResult(False, "At least one evidence asset is required")

        records = list(
            self._session.scalars(
                select(EvidenceAssetRecord).where(
                    EvidenceAssetRecord.id.in_(request.evidence_asset_ids),
                    EvidenceAssetRecord.citizen_id == principal.subject_ref,
                )
            )
        )
        if len(records) != len(set(request.evidence_asset_ids)):
            return EvidenceVerificationResult(False, "Evidence ownership or identity mismatch")
        if any(record.status != "verified" for record in records):
            return EvidenceVerificationResult(False, "All evidence must pass verification")
        if not any(record.asset_type in {"photo", "video"} for record in records):
            return EvidenceVerificationResult(False, "Photo or video evidence is required")
        if request.issue_type.strip().lower() in self._INFRASTRUCTURE_TYPES and not any(
            record.asset_type == "audio" for record in records
        ):
            return EvidenceVerificationResult(False, "A voice note is required for this issue")
        if not any(record.location_sample_id is not None for record in records):
            return EvidenceVerificationResult(False, "A captured location is required")
        return EvidenceVerificationResult(True)
