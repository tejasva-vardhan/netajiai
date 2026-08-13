import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.application.outbox import OutboxDispatcher, OutboxItem
from backend.app.infrastructure.db import Base, ComplaintEventRecord, ComplaintRecord, OutboxMessage
from backend.app.infrastructure.queues import KafkaOutboxPublisher, SqlAlchemyOutboxRepository


def _seed_outbox(engine):
    now = datetime.now(timezone.utc)
    complaint_id = uuid4()
    event_id = uuid4()
    message_id = uuid4()
    with Session(engine) as session:
        session.add(
            ComplaintRecord(
                id=complaint_id,
                citizen_id="citizen-outbox",
                creation_idempotency_key="create-outbox",
                status="received",
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ComplaintEventRecord(
                event_id=event_id,
                complaint_id=complaint_id,
                event_type="complaint.received",
                from_status=None,
                to_status="received",
                actor_type="citizen",
                actor_id="citizen-outbox",
                policy_version="test.v1",
                correlation_id="corr-outbox",
                idempotency_key="create-outbox",
                payload={"status": "received"},
                occurred_at=now,
            )
        )
        session.add(
            OutboxMessage(
                id=message_id,
                event_id=event_id,
                topic="complaint.lifecycle.v1",
                message_key=str(complaint_id),
                payload={"status": "received"},
                available_at=now,
                created_at=now,
            )
        )
        session.commit()
    return message_id


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.items: list[OutboxItem] = []
        self.fail = fail

    def publish(self, item: OutboxItem) -> None:
        if self.fail:
            raise RuntimeError("provider unavailable")
        self.items.append(item)


def test_outbox_dispatch_marks_success_and_keeps_failure_retryable():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    message_id = _seed_outbox(engine)
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        repository = SqlAlchemyOutboxRepository(session)
        publisher = RecordingPublisher()
        assert OutboxDispatcher(repository, publisher).dispatch_once(limit=10, now=now) == 1
        assert len(publisher.items) == 1
        record = session.get(OutboxMessage, message_id)
        assert record is not None and record.published_at is not None

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    message_id = _seed_outbox(engine)
    retry_now = datetime.now(timezone.utc)
    with Session(engine) as session:
        repository = SqlAlchemyOutboxRepository(session)
        assert OutboxDispatcher(repository, RecordingPublisher(fail=True)).dispatch_once(
            limit=1, now=retry_now
        ) == 0
        record = session.get(OutboxMessage, message_id)
        assert record is not None
        assert record.published_at is None
        assert record.last_error == "RuntimeError"
        assert record.attempts == 1


class FakeKafkaProducer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def produce(self, **kwargs):
        self.calls.append(kwargs)

    def flush(self):
        return 0


def test_kafka_publisher_sends_explicit_idempotent_message_envelope():
    client = FakeKafkaProducer()
    publisher = KafkaOutboxPublisher("kafka:29092", client=client)
    item = OutboxItem(
        uuid4(), uuid4(), "complaint.lifecycle.v1", "complaint-1", {"status": "received"}, 1
    )

    publisher.publish(item)

    assert len(client.calls) == 1
    body = json.loads(client.calls[0]["value"])
    assert body["message_id"] == str(item.message_id)
    assert body["event_id"] == str(item.event_id)
    assert body["payload"] == {"status": "received"}
    assert client.calls[0]["topic"] == item.topic
    assert client.calls[0]["key"] == item.message_key
