"""SQLAlchemy receipt storage for idempotent workflow signals."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.application.workflow_signals import (
    CitizenResolutionResponse,
    CitizenResolutionRepository,
    SignalKind,
    WorkflowSignalReceipt,
    WorkflowSignalRepository,
)
from backend.app.contracts.workflow_signals import CitizenResolutionOutcome
from backend.app.infrastructure.db import (
    CitizenResolutionResponseRecord,
    WorkflowSignalReceiptRecord,
)


class SqlAlchemyWorkflowSignalRepository(WorkflowSignalRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find(self, complaint_id: UUID, idempotency_key: str) -> WorkflowSignalReceipt | None:
        record = self._session.scalar(
            select(WorkflowSignalReceiptRecord).where(
                WorkflowSignalReceiptRecord.complaint_id == complaint_id,
                WorkflowSignalReceiptRecord.idempotency_key == idempotency_key,
            )
        )
        return self._view(record) if record is not None else None

    def reserve(
        self,
        *,
        complaint_id: UUID,
        signal_id: UUID,
        signal_kind: SignalKind,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> WorkflowSignalReceipt:
        existing = self.find(complaint_id, idempotency_key)
        if existing is not None:
            return existing
        record = WorkflowSignalReceiptRecord(
            complaint_id=complaint_id,
            signal_id=signal_id,
            signal_kind=signal_kind,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find(complaint_id, idempotency_key)
            if existing is None:
                raise
            return existing
        self._session.refresh(record)
        return self._view(record)

    def mark_sent(self, signal_id: UUID, *, now: datetime) -> WorkflowSignalReceipt:
        record = self._required(signal_id)
        record.status = "sent"
        record.last_error = None
        record.updated_at = now
        self._session.commit()
        self._session.refresh(record)
        return self._view(record)

    def mark_failed(
        self, signal_id: UUID, *, error_code: str, now: datetime
    ) -> WorkflowSignalReceipt:
        record = self._required(signal_id)
        record.status = "failed"
        record.last_error = error_code[:120]
        record.updated_at = now
        self._session.commit()
        self._session.refresh(record)
        return self._view(record)

    def _required(self, signal_id: UUID) -> WorkflowSignalReceiptRecord:
        record = self._session.scalar(
            select(WorkflowSignalReceiptRecord).where(
                WorkflowSignalReceiptRecord.signal_id == signal_id
            )
        )
        if record is None:
            raise ValueError("Workflow signal receipt was not found")
        return record

    @staticmethod
    def _view(record: WorkflowSignalReceiptRecord) -> WorkflowSignalReceipt:
        return WorkflowSignalReceipt(
            signal_id=record.signal_id,
            complaint_id=record.complaint_id,
            signal_kind=record.signal_kind,  # type: ignore[arg-type]
            request_fingerprint=record.request_fingerprint,
            status=record.status,  # type: ignore[arg-type]
        )


class SqlAlchemyCitizenResolutionRepository(CitizenResolutionRepository):
    """Persist citizen outcomes without storing a reason or private text."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find(
        self, complaint_id: UUID, idempotency_key: str
    ) -> CitizenResolutionResponse | None:
        record = self._session.scalar(
            select(CitizenResolutionResponseRecord).where(
                CitizenResolutionResponseRecord.complaint_id == complaint_id,
                CitizenResolutionResponseRecord.idempotency_key == idempotency_key,
            )
        )
        return self._view(record) if record is not None else None

    def latest(self, complaint_id: UUID) -> CitizenResolutionResponse | None:
        record = self._session.scalar(
            select(CitizenResolutionResponseRecord)
            .where(CitizenResolutionResponseRecord.complaint_id == complaint_id)
            .order_by(
                CitizenResolutionResponseRecord.created_at.desc(),
                CitizenResolutionResponseRecord.id.desc(),
            )
            .limit(1)
        )
        return self._view(record) if record is not None else None

    def reserve(
        self,
        *,
        response_id: UUID,
        complaint_id: UUID,
        signal_id: UUID,
        outcome: CitizenResolutionOutcome,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> CitizenResolutionResponse:
        existing = self.find(complaint_id, idempotency_key)
        if existing is not None:
            return existing
        record = CitizenResolutionResponseRecord(
            id=response_id,
            complaint_id=complaint_id,
            signal_id=signal_id,
            outcome=outcome,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            created_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find(complaint_id, idempotency_key)
            if existing is None:
                raise
            return existing
        self._session.refresh(record)
        return self._view(record)

    @staticmethod
    def _view(record: CitizenResolutionResponseRecord) -> CitizenResolutionResponse:
        return CitizenResolutionResponse(
            response_id=record.id,
            complaint_id=record.complaint_id,
            signal_id=record.signal_id,
            outcome=record.outcome,  # type: ignore[arg-type]
            request_fingerprint=record.request_fingerprint,
            idempotency_key=record.idempotency_key,
            created_at=record.created_at,
        )
