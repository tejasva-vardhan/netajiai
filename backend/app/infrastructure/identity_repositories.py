"""SQLAlchemy adapter for minimal identity-verification records."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.identity import (
    IdentityVerificationRecord,
    IdentityVerificationRepository,
)
from backend.app.contracts.identity import IdentityVerificationResult
from backend.app.infrastructure.db import IdentityVerificationRecord as IdentityRecord


class SqlAlchemyIdentityVerificationRepository(IdentityVerificationRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_reference_hash(
        self, reference_hash: str
    ) -> IdentityVerificationRecord | None:
        record = self._session.scalar(
            select(IdentityRecord).where(IdentityRecord.reference_hash == reference_hash)
        )
        return self._view(record) if record is not None else None

    def find_latest_for_subject(
        self, subject_ref: str
    ) -> IdentityVerificationRecord | None:
        record = self._session.scalar(
            select(IdentityRecord)
            .where(IdentityRecord.subject_ref == subject_ref)
            .order_by(IdentityRecord.created_at.desc())
            .limit(1)
        )
        return self._view(record) if record is not None else None

    def save(
        self,
        result: IdentityVerificationResult,
        *,
        reference_hash: str,
        retention_until: datetime | None,
        now: datetime,
    ) -> IdentityVerificationRecord:
        record = IdentityRecord(
            subject_ref=result.subject_ref,
            provider=result.provider,
            method=result.method,
            reference_hash=reference_hash,
            consent_id=result.consent_id,
            status=result.status,
            verified_claims=dict(result.verified_claims),
            verified_at=result.verified_at,
            expires_at=result.expires_at,
            retention_until=retention_until,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        self._session.commit()
        self._session.refresh(record)
        return self._view(record)

    @staticmethod
    def _view(record: IdentityRecord) -> IdentityVerificationRecord:
        return IdentityVerificationRecord(
            verification_id=record.id,
            subject_ref=record.subject_ref,
            status=record.status,
            provider=record.provider,
            method=record.method,
            consent_id=record.consent_id,
            verified_at=record.verified_at,
            expires_at=record.expires_at,
            retention_until=record.retention_until,
        )
