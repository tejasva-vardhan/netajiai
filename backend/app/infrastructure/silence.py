"""SQLAlchemy adapter for private, append-only silence facts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.application.silence import (
    SilenceEvent,
    SilenceEventConflict,
    SilenceEventRepository,
)
from backend.app.infrastructure.db import SilenceEventRecord


class SqlAlchemySilenceEventRepository(SilenceEventRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_idempotency_key(
        self, complaint_id: UUID, idempotency_key: str
    ) -> SilenceEvent | None:
        record = self._session.scalar(
            select(SilenceEventRecord).where(
                SilenceEventRecord.complaint_id == complaint_id,
                SilenceEventRecord.idempotency_key == idempotency_key,
            )
        )
        return self._view(record) if record is not None else None

    def reserve(
        self,
        *,
        event_id: UUID,
        complaint_id: UUID,
        workflow_id: str,
        reason_code: str,
        status: str,
        deadline_at: datetime,
        observed_at: datetime,
        escalation_level: int,
        escalation_count: int,
        policy_version: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> SilenceEvent:
        existing = self.find_by_idempotency_key(complaint_id, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise SilenceEventConflict(
                    "Silence event idempotency key belongs to another request"
                )
            return existing
        record = SilenceEventRecord(
            id=event_id,
            complaint_id=complaint_id,
            workflow_id=workflow_id,
            reason_code=reason_code,
            status=status,
            deadline_at=deadline_at,
            observed_at=observed_at,
            escalation_level=escalation_level,
            escalation_count=escalation_count,
            policy_version=policy_version,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find_by_idempotency_key(complaint_id, idempotency_key)
            if existing is None:
                raise
            if existing.request_fingerprint != request_fingerprint:
                raise SilenceEventConflict(
                    "Silence event idempotency key belongs to another request"
                )
            return existing
        self._session.refresh(record)
        return self._view(record)

    @staticmethod
    def _view(record: SilenceEventRecord) -> SilenceEvent:
        return SilenceEvent(
            event_id=record.id,
            complaint_id=record.complaint_id,
            workflow_id=record.workflow_id,
            reason_code=record.reason_code,
            status=record.status,
            deadline_at=record.deadline_at,
            observed_at=record.observed_at,
            escalation_level=record.escalation_level,
            escalation_count=record.escalation_count,
            policy_version=record.policy_version,
            request_fingerprint=record.request_fingerprint,
        )
