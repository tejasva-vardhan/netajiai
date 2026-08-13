"""SQLAlchemy persistence for citizen-scoped voice-draft request bindings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import UUID

from backend.app.application.voice_drafts import (
    StoredVoiceDraft,
    VoiceDraftRequestRepository,
)
from backend.app.infrastructure.db import VoiceDraftRequestRecord


class SqlAlchemyVoiceDraftRequestRepository(VoiceDraftRequestRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find(self, citizen_id: str, idempotency_key: str) -> StoredVoiceDraft | None:
        record = self._session.scalar(
            select(VoiceDraftRequestRecord).where(
                VoiceDraftRequestRecord.citizen_id == citizen_id,
                VoiceDraftRequestRecord.idempotency_key == idempotency_key,
            )
        )
        return self._view(record) if record is not None else None

    def persist(
        self,
        *,
        citizen_id: str,
        audio_asset_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> StoredVoiceDraft:
        record = VoiceDraftRequestRecord(
            citizen_id=citizen_id,
            audio_asset_id=audio_asset_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            created_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find(citizen_id, idempotency_key)
            if existing is None:
                raise
            return existing
        self._session.refresh(record)
        return self._view(record)

    @staticmethod
    def _view(record: VoiceDraftRequestRecord) -> StoredVoiceDraft:
        return StoredVoiceDraft(request_fingerprint=record.request_fingerprint)
