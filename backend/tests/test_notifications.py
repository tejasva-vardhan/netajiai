from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.application.notifications import (
    NotificationDeliveryService,
    NotificationIdempotencyConflict,
    NotificationMessage,
    NotificationUnavailable,
)
from backend.app.infrastructure.db import Base, NotificationDeliveryRecord
from backend.app.infrastructure.notifications import (
    FakeNotificationSender,
    SqlAlchemyNotificationDeliveryRepository,
)


def _engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _message(*, key: str = "complaint:1:receipt", destination: str = "citizen:1"):
    return NotificationMessage(
        channel="email",
        destination_ref=destination,
        template_key="complaint.received",
        template_version="v1",
        idempotency_key=key,
        context={"receipt_token": "opaque-token"},
        complaint_id=UUID("00000000-0000-0000-0000-000000000001"),
    )


def test_notification_delivery_is_durable_and_idempotent_without_storing_context():
    engine = _engine()
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    sender = FakeNotificationSender()
    with Session(engine) as session:
        service = NotificationDeliveryService(
            SqlAlchemyNotificationDeliveryRepository(session), sender
        )
        first = service.deliver(_message(), now=now)
        second = service.deliver(_message(key="complaint:1:receipt"), now=now)

        assert first.delivery_id == second.delivery_id
        assert first.status == "sent"
        assert first.attempts == 1
        assert len(sender.messages) == 1
        stored = session.get(NotificationDeliveryRecord, first.delivery_id)
        assert stored is not None
        assert stored.destination_ref_hash != "citizen:1"
        assert stored.last_error is None
        assert not hasattr(stored, "context")


def test_failed_delivery_can_retry_with_same_key_but_different_request_cannot():
    engine = _engine()
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)

    class FailingSender(FakeNotificationSender):
        def send(self, message):
            raise TimeoutError("provider timeout")

    with Session(engine) as session:
        message = _message()
        service = NotificationDeliveryService(
            SqlAlchemyNotificationDeliveryRepository(session), FailingSender()
        )
        with pytest.raises(NotificationUnavailable):
            service.deliver(message, now=now)
        failed = SqlAlchemyNotificationDeliveryRepository(session).find_by_idempotency_key(
            message.idempotency_key
        )
        assert failed is not None
        assert failed.status == "failed"
        assert failed.attempts == 1
        assert failed.last_error == "TimeoutError"

        with pytest.raises(NotificationIdempotencyConflict):
            service.deliver(_message(destination="citizen:other"), now=now)

    with Session(engine) as session:
        sender = FakeNotificationSender()
        retried = NotificationDeliveryService(
            SqlAlchemyNotificationDeliveryRepository(session), sender
        ).deliver(message, now=now)
        assert retried.status == "sent"
        assert retried.attempts == 2
        assert len(sender.messages) == 1
