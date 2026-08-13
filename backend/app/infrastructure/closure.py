"""Closure-proof adapters and redacted SQLAlchemy persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.application.closure import (
    ClosureProofClaim,
    ClosureProofConflict,
    ClosureProofRepository,
    ClosureProofType,
    ClosureProofVerification,
    ClosureProofVerifier,
    ClosureProofUnavailable,
)
from backend.app.infrastructure.db import ClosureProofClaimRecord


class UnconfiguredClosureProofVerifier(ClosureProofVerifier):
    """Fail-closed production default until an approved verifier is injected."""

    def verify(
        self,
        *,
        complaint_id: UUID,
        proof_type: ClosureProofType,
        proof_reference: str,
        submitted_by: str,
        now: datetime,
    ) -> ClosureProofVerification:
        del complaint_id, proof_type, proof_reference, submitted_by, now
        raise ClosureProofUnavailable("Closure proof verifier is not configured")


class FixtureClosureProofVerifier(ClosureProofVerifier):
    """Explicit test-only verifier; never use this adapter in production."""

    def verify(
        self,
        *,
        complaint_id: UUID,
        proof_type: ClosureProofType,
        proof_reference: str,
        submitted_by: str,
        now: datetime,
    ) -> ClosureProofVerification:
        del proof_type, submitted_by, now
        expected_prefix = f"fixture:closure:{complaint_id}:"
        if not proof_reference.startswith(expected_prefix):
            return ClosureProofVerification(
                accepted=False,
                verifier="fixture-closure-proof-v1",
                reason="The fixture proof is not bound to this complaint",
            )
        return ClosureProofVerification(
            accepted=True,
            verifier="fixture-closure-proof-v1",
        )


class SqlAlchemyClosureProofRepository(ClosureProofRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_idempotency_key(
        self, complaint_id: UUID, idempotency_key: str
    ) -> ClosureProofClaim | None:
        record = self._session.scalar(
            select(ClosureProofClaimRecord).where(
                ClosureProofClaimRecord.complaint_id == complaint_id,
                ClosureProofClaimRecord.idempotency_key == idempotency_key,
            )
        )
        return self._view(record) if record is not None else None

    def find_for_complaint(
        self, complaint_id: UUID, claim_id: UUID
    ) -> ClosureProofClaim | None:
        record = self._session.scalar(
            select(ClosureProofClaimRecord).where(
                ClosureProofClaimRecord.id == claim_id,
                ClosureProofClaimRecord.complaint_id == complaint_id,
            )
        )
        return self._view(record) if record is not None else None

    def find_by_reference_hash(
        self, complaint_id: UUID, proof_reference_hash: str
    ) -> ClosureProofClaim | None:
        record = self._session.scalar(
            select(ClosureProofClaimRecord).where(
                ClosureProofClaimRecord.complaint_id == complaint_id,
                ClosureProofClaimRecord.proof_reference_hash == proof_reference_hash,
            )
        )
        return self._view(record) if record is not None else None

    def reserve(
        self,
        *,
        claim_id: UUID,
        complaint_id: UUID,
        proof_type: ClosureProofType,
        proof_reference_hash: str,
        submitted_by: str,
        verifier: str,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> ClosureProofClaim:
        existing = self.find_by_idempotency_key(complaint_id, idempotency_key)
        if existing is not None:
            return existing
        record = ClosureProofClaimRecord(
            id=claim_id,
            complaint_id=complaint_id,
            proof_type=proof_type,
            proof_reference_hash=proof_reference_hash,
            submitted_by=submitted_by,
            verifier=verifier,
            status="accepted",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            verified_at=now,
            created_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find_by_idempotency_key(complaint_id, idempotency_key)
            if existing is not None:
                return existing
            duplicate = self.find_by_reference_hash(complaint_id, proof_reference_hash)
            if duplicate is not None:
                raise ClosureProofConflict(
                    "The closure proof reference has already been claimed"
                )
            raise
        self._session.refresh(record)
        return self._view(record)

    @staticmethod
    def _view(record: ClosureProofClaimRecord) -> ClosureProofClaim:
        return ClosureProofClaim(
            claim_id=record.id,
            complaint_id=record.complaint_id,
            proof_type=record.proof_type,  # type: ignore[arg-type]
            proof_reference_hash=record.proof_reference_hash,
            submitted_by=record.submitted_by,
            status=record.status,  # type: ignore[arg-type]
            verifier=record.verifier,
            request_fingerprint=record.request_fingerprint,
            verified_at=record.verified_at,
            created_at=record.created_at,
        )
