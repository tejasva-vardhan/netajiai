"""Provider-neutral notification delivery with durable idempotency."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol
from uuid import UUID


NotificationChannel = Literal["email", "sms", "whatsapp", "push", "voice"]
NotificationDeliveryStatus = Literal["pending", "sent", "failed"]


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    """A message addressed by an opaque server-side destination reference.

    ``destination_ref`` must not be a raw phone number or email address. The
    provider adapter resolves the opaque reference in its own protected
    boundary. ``context`` is transient rendering input and is never persisted
    by the delivery repository.
    """

    channel: NotificationChannel
    destination_ref: str
    template_key: str
    template_version: str
    idempotency_key: str
    context: Mapping[str, str]
    complaint_id: UUID | None = None

    def __post_init__(self) -> None:
        required = {
            "destination_ref": self.destination_ref,
            "template_key": self.template_key,
            "template_version": self.template_version,
            "idempotency_key": self.idempotency_key,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError("Notification fields are required: " + ", ".join(missing))
        if self.channel not in {"email", "sms", "whatsapp", "push", "voice"}:
            raise ValueError("Unsupported notification channel")
        if len(self.context) > 30:
            raise ValueError("Notification context is too large")


@dataclass(frozen=True, slots=True)
class NotificationProviderReceipt:
    provider: str
    receipt_ref: str


@dataclass(frozen=True, slots=True)
class NotificationDeliveryRecord:
    delivery_id: UUID
    complaint_id: UUID | None
    channel: NotificationChannel
    template_key: str
    template_version: str
    destination_ref_hash: str
    request_fingerprint: str
    status: NotificationDeliveryStatus
    provider: str | None
    provider_receipt: str | None
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None


class NotificationDeliveryRepository(Protocol):
    def find_by_idempotency_key(self, idempotency_key: str) -> NotificationDeliveryRecord | None: ...

    def reserve(
        self,
        message: NotificationMessage,
        *,
        destination_ref_hash: str,
        request_fingerprint: str,
        now: datetime,
    ) -> NotificationDeliveryRecord: ...

    def record_attempt(
        self, delivery_id: UUID, *, now: datetime
    ) -> NotificationDeliveryRecord: ...

    def mark_sent(
        self,
        delivery_id: UUID,
        receipt: NotificationProviderReceipt,
        *,
        now: datetime,
    ) -> NotificationDeliveryRecord: ...

    def mark_failed(
        self,
        delivery_id: UUID,
        *,
        error_code: str,
        now: datetime,
    ) -> NotificationDeliveryRecord: ...


class NotificationSender(Protocol):
    def send(self, message: NotificationMessage) -> NotificationProviderReceipt: ...


class NotificationIdempotencyConflict(ValueError):
    """The same key was reused for a different notification request."""


class NotificationUnavailable(RuntimeError):
    """The provider failed; the durable failed record remains retryable."""


class NotificationDeliveryService:
    """Persist delivery state around a provider call without storing message PII."""

    def __init__(
        self,
        repository: NotificationDeliveryRepository,
        sender: NotificationSender,
    ) -> None:
        self._repository = repository
        self._sender = sender

    def deliver(self, message: NotificationMessage, *, now: datetime) -> NotificationDeliveryRecord:
        destination_hash = _sha256(message.destination_ref)
        fingerprint = _request_fingerprint(message)
        existing = self._repository.find_by_idempotency_key(message.idempotency_key)
        if existing is not None and existing.request_fingerprint != fingerprint:
            raise NotificationIdempotencyConflict(
                "Notification idempotency key belongs to another request"
            )
        if existing is not None and existing.status == "sent":
            return existing

        record = self._repository.reserve(
            message,
            destination_ref_hash=destination_hash,
            request_fingerprint=fingerprint,
            now=now,
        )
        if record.request_fingerprint != fingerprint:
            raise NotificationIdempotencyConflict(
                "Notification idempotency key belongs to another request"
            )
        record = self._repository.record_attempt(record.delivery_id, now=now)
        try:
            receipt = self._sender.send(message)
        except Exception as exc:
            self._repository.mark_failed(
                record.delivery_id,
                error_code=type(exc).__name__[:120],
                now=now,
            )
            raise NotificationUnavailable(
                "Notification provider is temporarily unavailable"
            ) from exc
        return self._repository.mark_sent(record.delivery_id, receipt, now=now)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_fingerprint(message: NotificationMessage) -> str:
    canonical = json.dumps(
        {
            "channel": message.channel,
            "destination_ref": message.destination_ref,
            "template_key": message.template_key,
            "template_version": message.template_version,
            "context": dict(sorted(message.context.items())),
            "complaint_id": str(message.complaint_id) if message.complaint_id else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(canonical)
