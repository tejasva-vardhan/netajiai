from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.config import Settings
from backend.app.infrastructure.db import Base, ComplaintEventRecord, ComplaintRecord, OutboxMessage
from backend.app.infrastructure.temporal_client import temporal_connect_kwargs
from backend.app.workers.outbox import run_outbox_worker
from backend.app.workers.temporal import run_temporal_worker


def _outbox_engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    complaint_id = uuid4()
    event_id = uuid4()
    message_id = uuid4()
    with Session(engine) as session:
        session.add(
            ComplaintRecord(
                id=complaint_id,
                citizen_id="worker-test",
                creation_idempotency_key="worker-create",
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
                actor_id="worker-test",
                policy_version="test.v1",
                correlation_id="worker-test",
                idempotency_key="worker-create",
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
    return engine, sessionmaker(engine), message_id


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.items = []
        self.fail = fail

    def publish(self, item) -> None:
        if self.fail:
            raise RuntimeError("queue unavailable")
        self.items.append(item)


@pytest.mark.asyncio
async def test_outbox_worker_dispatches_a_batch_and_stops_cleanly():
    engine, session_factory, message_id = _outbox_engine()
    publisher = RecordingPublisher()
    stop_event = asyncio.Event()
    delays: list[float] = []

    async def stop_after_one_poll(delay: float) -> None:
        delays.append(delay)
        stop_event.set()

    settings = Settings(
        outbox_batch_size=10,
        outbox_poll_interval_seconds=0.25,
        outbox_error_backoff_seconds=1.0,
    )
    await run_outbox_worker(
        settings,
        session_factory,
        publisher,
        stop_event=stop_event,
        sleeper=stop_after_one_poll,
    )

    assert len(publisher.items) == 1
    assert delays == [0.25]
    with Session(engine) as session:
        record = session.get(OutboxMessage, message_id)
        assert record is not None and record.published_at is not None


@pytest.mark.asyncio
async def test_outbox_worker_records_provider_failure_and_uses_error_backoff():
    engine, session_factory, message_id = _outbox_engine()
    stop_event = asyncio.Event()
    delays: list[float] = []

    async def stop_after_failure(delay: float) -> None:
        delays.append(delay)
        stop_event.set()

    await run_outbox_worker(
        Settings(outbox_poll_interval_seconds=0.25, outbox_error_backoff_seconds=1.5),
        session_factory,
        RecordingPublisher(fail=True),
        stop_event=stop_event,
        sleeper=stop_after_failure,
    )

    assert delays == [1.5]
    with Session(engine) as session:
        record = session.get(OutboxMessage, message_id)
        assert record is not None
        assert record.published_at is None
        assert record.last_error == "RuntimeError"


def test_temporal_connect_options_never_require_local_cloud_credentials():
    options = temporal_connect_kwargs(
        Settings(temporal_target="localhost:7233", temporal_namespace="default")
    )

    assert options == {
        "target_host": "localhost:7233",
        "namespace": "default",
    }


@pytest.mark.asyncio
async def test_temporal_worker_shutdown_is_graceful_and_injected():
    stop_event = asyncio.Event()

    class FakeWorker:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.shutdown_complete = asyncio.Event()
            self.shutdown_called = False

        async def run(self):
            self.started.set()
            await self.shutdown_complete.wait()

        async def shutdown(self):
            self.shutdown_called = True
            self.shutdown_complete.set()

    fake_worker = FakeWorker()

    async def connector(settings):
        assert settings.temporal_target == "temporal.example:7233"
        return object()

    def worker_factory(client, session_factory):
        return fake_worker

    task = asyncio.create_task(
        run_temporal_worker(
            Settings(
                temporal_target="temporal.example:7233",
                temporal_namespace="ai-neta",
                temporal_api_key="test-only",
                temporal_task_queue="ai-neta-complaints",
            ),
            sessionmaker(create_engine("sqlite+pysqlite:///:memory:")),
            stop_event=stop_event,
            connector=connector,
            worker_factory=worker_factory,
        )
    )
    await fake_worker.started.wait()
    stop_event.set()
    await task

    assert fake_worker.shutdown_called
