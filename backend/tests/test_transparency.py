from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.contracts.complaints import CreateComplaintRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.domain.complaints import ComplaintAggregate
from backend.app.infrastructure.db import Base, ComplaintRecord
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository
from backend.app.application.routing import RoutingDecision


def _engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed_complaints(engine) -> None:
    with Session(engine) as session:
        repository = SqlAlchemyComplaintSubmissionRepository(session)
        for index in range(2):
            complaint_id = uuid4()
            repository.persist_received(
                ComplaintAggregate.receive(
                    complaint_id,
                    actor_type="citizen",
                    actor_id=f"citizen:{index}",
                    policy_version="test.v1",
                    correlation_id=f"corr:{index}",
                    idempotency_key=f"transparency:{index}",
                ),
                CreateComplaintRequest(
                    issue_type="streetlight",
                    description="private complaint description",
                    language="hi-en",
                    evidence_asset_ids=[uuid4()],
                    citizen_confirmation=True,
                ),
                AuthenticatedPrincipal(f"citizen:{index}", identity_verified=True),
                RoutingDecision(
                    state="mapping_in_progress" if index == 0 else "active",
                    jurisdiction_code=None,
                    snapshot_ref=None,
                    reason_code="test",
                ),
            )
            record = session.get(ComplaintRecord, complaint_id)
            assert record is not None
            record.escalation_level = index
            record.updated_at = datetime(2026, 8, 10, 12, index, tzinfo=timezone.utc)
            session.commit()


def test_public_transparency_is_disabled_by_default():
    response = TestClient(create_app(Settings(environment="test"))).get(
        "/api/v1/public/transparency"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Public transparency is not enabled"


def test_public_transparency_returns_only_aggregate_facts_when_enabled():
    engine = _engine()
    _seed_complaints(engine)
    app = create_app(
        Settings(
            environment="test",
            public_transparency_enabled=True,
            public_transparency_policy_version="transparency-test.v1",
        ),
        session_factory=sessionmaker(engine),
    )

    response = TestClient(app).get("/api/v1/public/transparency")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "policy_version",
        "generated_at",
        "last_updated_at",
        "total_complaints",
        "status_counts",
        "execution_zone_counts",
        "escalated_count",
        "mapping_in_progress_count",
    }
    assert payload["policy_version"] == "transparency-test.v1"
    assert payload["total_complaints"] == 2
    assert payload["status_counts"] == {"received": 2}
    assert payload["execution_zone_counts"] == {
        "mapping_in_progress": 1,
        "active": 1,
    }
    assert payload["escalated_count"] == 1
    assert payload["mapping_in_progress_count"] == 1
    assert "citizen_id" not in response.text
    assert "private complaint description" not in response.text
