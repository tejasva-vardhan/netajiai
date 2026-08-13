from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.complaints import ComplaintAggregate, ComplaintStatus
from backend.app.infrastructure.db import (
    Base,
    ComplaintEventRecord,
    ComplaintRecord,
    OutboxMessage,
)
from backend.app.infrastructure.outbox import append_event_and_outbox


def test_event_and_outbox_are_committed_together():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    complaint_id = uuid4()
    now = datetime.now(timezone.utc)

    aggregate = ComplaintAggregate(complaint_id)
    event = aggregate.transition(
        ComplaintStatus.VERIFYING,
        actor_type="system",
        actor_id="test",
        policy_version="policy.test.v1",
        correlation_id="corr-test",
        idempotency_key="verify-1",
    )
    assert event is not None

    with Session(engine) as session:
        session.add(
            ComplaintRecord(
                id=complaint_id,
                citizen_id="citizen-test",
                creation_idempotency_key="create-test",
                status=aggregate.status.value,
                version=aggregate.version,
                created_at=now,
                updated_at=now,
            )
        )
        append_event_and_outbox(
            session,
            event,
            topic="complaint.lifecycle.v1",
            payload={"complaint_id": str(complaint_id), "status": "verifying"},
        )
        session.commit()

        assert session.scalar(
            select(ComplaintEventRecord).where(ComplaintEventRecord.event_id == event.event_id)
        ).idempotency_key == "verify-1"
        assert session.scalar(
            select(OutboxMessage).where(OutboxMessage.event_id == event.event_id)
        )
