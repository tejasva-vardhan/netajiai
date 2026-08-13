"""Notification delivery repository and safe provider fixtures."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.application.notifications import (
    NotificationDeliveryRecord,
    NotificationDeliveryRepository,
    NotificationMessage,
    NotificationProviderReceipt,
    NotificationSender,
)
from backend.app.infrastructure.db import NotificationDeliveryRecord as NotificationRecord


class SqlAlchemyNotificationDeliveryRepository(NotificationDeliveryRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_idempotency_key(self, idempotency_key: str) -> NotificationDeliveryRecord | None:
        record = self._session.scalar(
            select(NotificationRecord).where(
                NotificationRecord.idempotency_key == idempotency_key
            )
        )
        return self._view(record) if record is not None else None

    def reserve(
        self,
        message: NotificationMessage,
        *,
        destination_ref_hash: str,
        request_fingerprint: str,
        now: datetime,
    ) -> NotificationDeliveryRecord:
        existing = self.find_by_idempotency_key(message.idempotency_key)
        if existing is not None:
            return existing
        record = NotificationRecord(
            complaint_id=message.complaint_id,
            destination_ref_hash=destination_ref_hash,
            channel=message.channel,
            template_key=message.template_key,
            template_version=message.template_version,
            idempotency_key=message.idempotency_key,
            request_fingerprint=request_fingerprint,
            status="pending",
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find_by_idempotency_key(message.idempotency_key)
            if existing is None:
                raise
            return existing
        self._session.refresh(record)
        return self._view(record)

    def record_attempt(self, delivery_id: UUID, *, now: datetime) -> NotificationDeliveryRecord:
        record = self._required(delivery_id)
        record.attempts += 1
        record.status = "pending"
        record.updated_at = now
        record.last_error = None
        self._session.commit()
        self._session.refresh(record)
        return self._view(record)

    def mark_sent(
        self,
        delivery_id: UUID,
        receipt: NotificationProviderReceipt,
        *,
        now: datetime,
    ) -> NotificationDeliveryRecord:
        record = self._required(delivery_id)
        record.status = "sent"
        record.provider = receipt.provider
        record.provider_receipt = receipt.receipt_ref
        record.last_error = None
        record.updated_at = now
        record.sent_at = now
        self._session.commit()
        self._session.refresh(record)
        return self._view(record)

    def mark_failed(
        self,
        delivery_id: UUID,
        *,
        error_code: str,
        now: datetime,
    ) -> NotificationDeliveryRecord:
        record = self._required(delivery_id)
        record.status = "failed"
        record.last_error = error_code[:120]
        record.updated_at = now
        self._session.commit()
        self._session.refresh(record)
        return self._view(record)

    def _required(self, delivery_id: UUID) -> NotificationRecord:
        record = self._session.get(NotificationRecord, delivery_id)
        if record is None:
            raise ValueError("Notification delivery was not found")
        return record

    @staticmethod
    def _view(record: NotificationRecord) -> NotificationDeliveryRecord:
        return NotificationDeliveryRecord(
            delivery_id=record.id,
            complaint_id=record.complaint_id,
            channel=record.channel,  # type: ignore[arg-type]
            template_key=record.template_key,
            template_version=record.template_version,
            destination_ref_hash=record.destination_ref_hash,
            request_fingerprint=record.request_fingerprint,
            status=record.status,  # type: ignore[arg-type]
            provider=record.provider,
            provider_receipt=record.provider_receipt,
            attempts=record.attempts,
            last_error=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
            sent_at=record.sent_at,
        )


class UnconfiguredNotificationSender(NotificationSender):
    def send(self, message: NotificationMessage) -> NotificationProviderReceipt:
        del message
        raise RuntimeError("Notification provider is not configured")


class FakeNotificationSender(NotificationSender):
    """Deterministic test sender; it never contacts a real destination."""

    def __init__(self, *, provider: str = "fake-notifications") -> None:
        self.provider = provider
        self.messages: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> NotificationProviderReceipt:
        self.messages.append(message)
        receipt = sha256(message.idempotency_key.encode("utf-8")).hexdigest()[:24]
        return NotificationProviderReceipt(provider=self.provider, receipt_ref=receipt)
