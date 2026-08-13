from datetime import datetime, timedelta, timezone
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


def test_admin_complaint_list_is_capability_protected_and_redacted():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
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
                    idempotency_key=f"create:{index}",
                ),
                CreateComplaintRequest(
                    issue_type="pothole",
                    description="private citizen description",
                    language="hi-en",
                    jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
                    evidence_asset_ids=[uuid4()],
                    citizen_confirmation=True,
                ),
                AuthenticatedPrincipal(f"citizen:{index}", identity_verified=True),
                RoutingDecision(
                    state="mapping_in_progress" if index == 0 else "active",
                    jurisdiction_code=None if index == 0 else "IN-MP-SYNTHETIC-BHOPAL",
                    snapshot_ref="test",
                    reason_code="test",
                ),
            )
            record = session.get(ComplaintRecord, complaint_id)
            assert record is not None
            record.updated_at = now - timedelta(minutes=index)
            session.commit()

    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "operator:1", roles=frozenset({"operator"})
        ),
    )
    response = TestClient(app).get("/api/v1/admin/complaints?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["next_cursor"]
    assert "description" not in payload["items"][0]
    assert "citizen_id" not in payload["items"][0]

    next_response = TestClient(app).get(
        "/api/v1/admin/complaints?limit=1&cursor=" + payload["next_cursor"]
    )
    assert next_response.status_code == 200
    assert len(next_response.json()["items"]) == 1

    mapping_response = TestClient(app).get(
        "/api/v1/admin/complaints?execution_zone_state=mapping_in_progress"
    )
    assert mapping_response.status_code == 200
    assert len(mapping_response.json()["items"]) == 1
    assert mapping_response.json()["items"][0]["execution_zone_state"] == "mapping_in_progress"


def test_admin_complaint_list_rejects_citizen_principal():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal("citizen:1"),
    )

    response = TestClient(app).get("/api/v1/admin/complaints")

    assert response.status_code == 403


def test_admin_overview_returns_aggregate_facts_without_citizen_data():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
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
                    idempotency_key=f"overview-create:{index}",
                ),
                CreateComplaintRequest(
                    issue_type="road",
                    description="private citizen description",
                    language="hi-en",
                    evidence_asset_ids=[uuid4()],
                    citizen_confirmation=True,
                ),
                AuthenticatedPrincipal(f"citizen:{index}", identity_verified=True),
                RoutingDecision(
                    state="mapping_in_progress" if index == 0 else "active",
                    jurisdiction_code=None,
                    snapshot_ref="test",
                    reason_code="test",
                ),
            )
            record = session.get(ComplaintRecord, complaint_id)
            assert record is not None
            record.updated_at = now
            if index == 1:
                record.escalation_level = 1
            session.commit()

    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "operator:1", roles=frozenset({"operator"})
        ),
    )
    response = TestClient(app).get("/api/v1/admin/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_complaints"] == 2
    assert payload["mapping_in_progress_count"] == 1
    assert payload["escalated_count"] == 1
    assert payload["execution_zone_counts"] == {
        "mapping_in_progress": 1,
        "active": 1,
    }
    assert "description" not in payload
    assert "citizen_id" not in payload
