from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.application.silence import (
    SilenceEventConflict,
    silence_request_fingerprint,
)
from backend.app.infrastructure.db import Base, SilenceEventRecord
from backend.app.infrastructure.silence import SqlAlchemySilenceEventRepository
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository
from backend.app.workflows.activities import build_silence_activity
from backend.app.workflows.complaint_lifecycle import SilenceActivityInput
from backend.tests.test_workflows import _seed_complaint


@pytest.mark.asyncio
async def test_silence_activity_is_private_and_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine)
    factory = sessionmaker(engine)
    record_silence = build_silence_activity(factory)
    deadline = datetime.now(timezone.utc)
    input = SilenceActivityInput(
        complaint_id=complaint_id,
        workflow_id=f"workflow:{complaint_id}",
        reason_code="department_response_deadline",
        status="awaiting_response",
        deadline_at=deadline,
        observed_at=deadline + timedelta(seconds=1),
        escalation_level=0,
        escalation_count=0,
        policy_version="test.v1",
        idempotency_key="silence-1",
    )

    first = await record_silence(input)
    second = await record_silence(input)

    assert first == second
    with Session(engine) as session:
        rows = session.execute(select(SilenceEventRecord)).all()
    assert len(rows) == 1
    with Session(engine) as session:
        tracking = SqlAlchemyComplaintSubmissionRepository(session).find_owned(
            "citizen-workflow", complaint_id
        )
    assert tracking is not None
    assert tracking.timeline[-1].event_type == "complaint.silence_deadline_breached"
    assert tracking.timeline[-1].reason_code == "department_response_deadline"
    assert tracking.timeline[-1].status.value == "awaiting_response"


def test_silence_repository_rejects_reused_key_for_different_fingerprint():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        repository = SqlAlchemySilenceEventRepository(session)
        first_fingerprint = silence_request_fingerprint(
            complaint_id=complaint_id,
            workflow_id="workflow:test",
            reason_code="department_response_deadline",
            status="awaiting_response",
            deadline_at=now,
            escalation_level=0,
            escalation_count=0,
            policy_version="test.v1",
        )
        repository.reserve(
            event_id=uuid4(),
            complaint_id=complaint_id,
            workflow_id="workflow:test",
            reason_code="department_response_deadline",
            status="awaiting_response",
            deadline_at=now,
            observed_at=now,
            escalation_level=0,
            escalation_count=0,
            policy_version="test.v1",
            idempotency_key="same-key",
            request_fingerprint=first_fingerprint,
        )

        with pytest.raises(SilenceEventConflict):
            repository.reserve(
                event_id=uuid4(),
                complaint_id=complaint_id,
                workflow_id="workflow:test",
                reason_code="post_escalation_response_deadline",
                status="escalated",
                deadline_at=now,
                observed_at=now,
                escalation_level=1,
                escalation_count=1,
                policy_version="test.v1",
                idempotency_key="same-key",
                request_fingerprint="b" * 64,
            )
