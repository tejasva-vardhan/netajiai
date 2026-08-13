from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.application.disclosure import (
    DisclosureConsentConflict,
    DisclosureConsentService,
    DisclosurePolicyUnavailable,
)
from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.contracts.complaints import DisclosureConsentRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import Base, ComplaintEventRecord, ComplaintRecord, OutboxMessage
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository


def _database() -> tuple[Engine, str]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    complaint_id = uuid4()
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            ComplaintRecord(
                id=complaint_id,
                citizen_id="oidc:citizen-disclosure",
                creation_idempotency_key="create-disclosure",
                status="received",
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return engine, str(complaint_id)


def _request(mode: str = "verified_citizen") -> DisclosureConsentRequest:
    return DisclosureConsentRequest(
        mode=mode, consent=True
    )


def test_private_disclosure_choice_is_explicit_one_time_and_audited():
    engine, complaint_id = _database()
    principal = AuthenticatedPrincipal(subject_ref="oidc:citizen-disclosure")

    with Session(engine) as session:
        service = DisclosureConsentService(SqlAlchemyComplaintSubmissionRepository(session))
        result = service.record(
            principal,
            UUID(complaint_id),
            _request(),
            idempotency_key="disclosure-1",
            correlation_id="corr-disclosure",
        )

    assert result.disclosure_mode == "verified_citizen"
    assert result.public_disclosure_eligible is False
    assert result.policy_version == "disclosure-policy.v1"

    with Session(engine) as session:
        event = session.scalar(
            select(ComplaintEventRecord).where(
                ComplaintEventRecord.event_type == "complaint.disclosure_consented"
            )
        )
        assert event is not None
        outbox = session.scalar(select(OutboxMessage).where(OutboxMessage.event_id == event.event_id))
        assert event.payload["disclosure_mode"] == "verified_citizen"
        assert outbox is not None


def test_disclosure_choice_replay_and_second_choice_are_safe():
    engine, complaint_id = _database()
    principal = AuthenticatedPrincipal(subject_ref="oidc:citizen-disclosure")

    with Session(engine) as session:
        service = DisclosureConsentService(SqlAlchemyComplaintSubmissionRepository(session))
        first = service.record(
            principal,
            UUID(complaint_id),
            _request(),
            idempotency_key="disclosure-1",
            correlation_id="corr-disclosure",
        )
        replay = service.record(
            principal,
            UUID(complaint_id),
            _request(),
            idempotency_key="disclosure-1",
            correlation_id="corr-disclosure-retry",
        )
        assert replay == first

        with pytest.raises(DisclosureConsentConflict, match="already"):
            service.record(
                principal,
                UUID(complaint_id),
                _request(),
                idempotency_key="disclosure-2",
                correlation_id="corr-disclosure-second",
            )


def test_public_disclosure_remains_disabled_until_policy_is_enabled():
    engine, complaint_id = _database()
    principal = AuthenticatedPrincipal(subject_ref="oidc:citizen-disclosure")
    with Session(engine) as session:
        service = DisclosureConsentService(SqlAlchemyComplaintSubmissionRepository(session))
        with pytest.raises(DisclosurePolicyUnavailable):
            service.record(
                principal,
                UUID(complaint_id),
                _request("public_name"),
                idempotency_key="disclosure-public",
                correlation_id="corr-disclosure-public",
            )


def test_public_disclosure_requires_explicit_deployment_flag():
    assert Settings.from_env({}).public_disclosure_enabled is False


def test_disclosure_consent_http_command_is_authenticated_and_idempotent():
    engine, complaint_id = _database()
    client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                subject_ref="oidc:citizen-disclosure"
            ),
        )
    )
    headers = {
        "Authorization": "Bearer test",
        "Idempotency-Key": "disclosure-http-1",
    }
    body = {
        "mode": "verified_citizen",
        "consent": True,
    }

    first = client.post(
        f"/api/v1/complaints/{complaint_id}/disclosure-consent",
        headers=headers,
        json=body,
    )
    replay = client.post(
        f"/api/v1/complaints/{complaint_id}/disclosure-consent",
        headers=headers,
        json=body,
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
