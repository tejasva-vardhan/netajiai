"""SQLAlchemy adapter for private department-reply facts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.application.department_replies import (
    DepartmentReply,
    DepartmentReplyRepository,
    ReplyClassification,
)
from backend.app.infrastructure.db import DepartmentReplyRecord


class SqlAlchemyDepartmentReplyRepository(DepartmentReplyRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_idempotency_key(
        self, complaint_id: UUID, idempotency_key: str
    ) -> DepartmentReply | None:
        record = self._session.scalar(
            select(DepartmentReplyRecord).where(
                DepartmentReplyRecord.complaint_id == complaint_id,
                DepartmentReplyRecord.idempotency_key == idempotency_key,
            )
        )
        return self._view(record) if record is not None else None

    def has_text_hash(self, complaint_id: UUID, response_text_hash: str) -> bool:
        return (
            self._session.scalar(
                select(DepartmentReplyRecord.id).where(
                    DepartmentReplyRecord.complaint_id == complaint_id,
                    DepartmentReplyRecord.response_text_hash == response_text_hash,
                )
            )
            is not None
        )

    def reserve(
        self,
        *,
        reply_id: UUID,
        complaint_id: UUID,
        submitted_by: str,
        outcome: str,
        response_text: str | None,
        response_text_hash: str | None,
        classification: ReplyClassification,
        classification_reason: str,
        classification_policy_version: str,
        proof_claim_id: UUID | None,
        idempotency_key: str,
        request_fingerprint: str,
        received_at: datetime,
    ) -> DepartmentReply:
        existing = self.find_by_idempotency_key(complaint_id, idempotency_key)
        if existing is not None:
            return existing
        record = DepartmentReplyRecord(
            id=reply_id,
            complaint_id=complaint_id,
            submitted_by=submitted_by,
            outcome=outcome,
            response_text=response_text,
            response_text_hash=response_text_hash,
            classification=classification,
            classification_reason=classification_reason,
            classification_policy_version=classification_policy_version,
            proof_claim_id=proof_claim_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            received_at=received_at,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find_by_idempotency_key(complaint_id, idempotency_key)
            if existing is None:
                raise
            return existing
        self._session.refresh(record)
        return self._view(record)

    @staticmethod
    def _view(record: DepartmentReplyRecord) -> DepartmentReply:
        return DepartmentReply(
            reply_id=record.id,
            complaint_id=record.complaint_id,
            classification=record.classification,  # type: ignore[arg-type]
            classification_reason=record.classification_reason,
            response_text_hash=record.response_text_hash,
            request_fingerprint=record.request_fingerprint,
        )
