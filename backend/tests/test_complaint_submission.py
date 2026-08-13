from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from uuid import uuid4

from backend.app.api.main import create_app
import pytest

from backend.app.application.complaints import (
    ComplaintSubmissionConflict,
    ComplaintSubmissionService,
    ComplaintTransitionService,
)
from backend.app.config import Settings
from backend.app.contracts.complaints import CreateComplaintRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import (
    Base,
    ComplaintEvidenceRecord,
    ComplaintEventRecord,
    ComplaintRecord,
)
from backend.app.infrastructure.evidence import AcceptedEvidenceFixture
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository
from backend.app.application.routing import RoutingDecision
from backend.app.application.sla import SyntheticSlaPolicy
from backend.app.domain.complaints import ComplaintAggregate, ComplaintStatus


def _request_body() -> dict:
    evidence_asset_id = str(uuid4())
    return {
        "issue_type": "pothole",
        "description": "A large pothole is blocking the lane.",
        "language": "hi-en",
        "jurisdiction_code": "IN-DL-001",
        "evidence_asset_ids": [evidence_asset_id],
        "citizen_confirmation": True,
    }


def test_complaint_creation_persists_event_and_outbox_and_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-1", identity_verified=True)

    with Session(engine) as session:
        service = ComplaintSubmissionService(
            SqlAlchemyComplaintSubmissionRepository(session), AcceptedEvidenceFixture()
        )
        request = CreateComplaintRequest(**_request_body())
        first = service.create(
            principal, request, idempotency_key="create-1", correlation_id="corr-1"
        )
        second = service.create(
            principal, request, idempotency_key="create-1", correlation_id="corr-retry"
        )

        assert first == second
        assert session.scalar(select(func.count(ComplaintRecord.id))) == 1
        assert session.scalar(select(func.count(ComplaintEventRecord.event_id))) == 1
        links = list(
            session.scalars(
                select(ComplaintEvidenceRecord).where(
                    ComplaintEvidenceRecord.complaint_id == first.complaint_id
                )
            )
        )
        assert len(links) == 1

        owned = SqlAlchemyComplaintSubmissionRepository(session).find_owned(
            principal.subject_ref, first.complaint_id
        )
        assert owned is not None
        assert [item.status for item in owned.timeline] == [ComplaintStatus.RECEIVED]
        assert not hasattr(owned.timeline[0], "actor_id")

        ComplaintTransitionService(
            SqlAlchemyComplaintSubmissionRepository(session)
        ).transition(
            AuthenticatedPrincipal(
                "temporal-workflow", roles=frozenset({"workflow"}), identity_verified=True
            ),
            first.complaint_id,
            ComplaintStatus.VERIFYING,
            idempotency_key="timeline-transition-1",
            correlation_id="timeline-corr-1",
        )
        updated = SqlAlchemyComplaintSubmissionRepository(session).find_owned(
            principal.subject_ref, first.complaint_id
        )
        assert updated is not None
        assert [item.status for item in updated.timeline] == [
            ComplaintStatus.RECEIVED,
            ComplaintStatus.VERIFYING,
        ]

        with pytest.raises(ComplaintSubmissionConflict, match="belongs to another request"):
            service.create(
                principal,
                request.model_copy(update={"description": "A different issue."}),
                idempotency_key="create-1",
                correlation_id="corr-conflict",
            )


def test_complaint_repository_recovers_from_duplicate_key_during_flush():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-race", identity_verified=True)
    request = CreateComplaintRequest(**_request_body())
    routing = RoutingDecision.mapping_in_progress(reason_code="test_fixture")

    with Session(engine) as winner_session:
        winner = SqlAlchemyComplaintSubmissionRepository(winner_session).persist_received(
            ComplaintAggregate.receive(
                uuid4(),
                actor_type="citizen",
                actor_id=principal.subject_ref,
                policy_version="test.v1",
                correlation_id="winner-correlation",
                idempotency_key="race-create-1",
            ),
            request,
            principal,
            routing,
            request_fingerprint="request-fingerprint-1",
        )

    with Session(engine) as retry_session:
        repository = SqlAlchemyComplaintSubmissionRepository(retry_session)
        retry = repository.persist_received(
            ComplaintAggregate.receive(
                uuid4(),
                actor_type="citizen",
                actor_id=principal.subject_ref,
                policy_version="test.v1",
                correlation_id="retry-correlation",
                idempotency_key="race-create-1",
            ),
            request,
            principal,
            routing,
            request_fingerprint="request-fingerprint-1",
        )

        assert retry.complaint_id == winner.complaint_id
        assert retry.status == winner.status

        with pytest.raises(ComplaintSubmissionConflict, match="belongs to another request"):
            repository.persist_received(
                ComplaintAggregate.receive(
                    uuid4(),
                    actor_type="citizen",
                    actor_id=principal.subject_ref,
                    policy_version="test.v1",
                    correlation_id="conflict-correlation",
                    idempotency_key="race-create-1",
                ),
                request,
                principal,
                routing,
                request_fingerprint="different-fingerprint",
            )

    with Session(engine) as session:
        assert session.scalar(select(func.count(ComplaintRecord.id))) == 1
        assert session.scalar(select(func.count(ComplaintEventRecord.event_id))) == 1


def test_complaint_creation_uses_server_owned_routing_decision():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-routing", identity_verified=True)

    class ActiveRouting:
        def resolve(self, resolved_principal, evidence_asset_ids):
            assert resolved_principal == principal
            assert evidence_asset_ids
            return RoutingDecision(
                state="active",
                jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
                snapshot_ref="synthetic-mp-routing-v1",
                reason_code="test_fixture",
            )

    with Session(engine) as session:
        service = ComplaintSubmissionService(
            SqlAlchemyComplaintSubmissionRepository(session),
            AcceptedEvidenceFixture(),
            routing_resolver=ActiveRouting(),
        )
        response = service.create(
            principal,
            CreateComplaintRequest(**_request_body()),
            idempotency_key="routing-create-1",
            correlation_id="routing-corr-1",
        )
        record = session.get(ComplaintRecord, response.complaint_id)

    assert record is not None
    assert record.execution_zone_state == "active"
    assert record.jurisdiction_code == "IN-MP-SYNTHETIC-BHOPAL"


def test_complaint_creation_persists_the_versioned_sla_snapshot():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-sla", identity_verified=True)

    with Session(engine) as session:
        service = ComplaintSubmissionService(
            SqlAlchemyComplaintSubmissionRepository(session),
            AcceptedEvidenceFixture(),
            sla_policy=SyntheticSlaPolicy(),
        )
        response = service.create(
            principal,
            CreateComplaintRequest(**{**_request_body(), "issue_type": "water"}),
            idempotency_key="sla-create-1",
            correlation_id="sla-corr-1",
        )
        record = session.get(ComplaintRecord, response.complaint_id)
        event = session.scalar(
            select(ComplaintEventRecord).where(
                ComplaintEventRecord.complaint_id == response.complaint_id
            )
        )

    assert record is not None
    assert record.sla_policy_version == "synthetic-sla.v1"
    assert record.response_timeout_seconds == 48 * 60 * 60
    assert record.post_escalation_timeout_seconds == 30 * 24 * 60 * 60
    assert event is not None
    assert event.payload["sla_policy_version"] == "synthetic-sla.v1"
    assert event.payload["response_timeout_seconds"] == 48 * 60 * 60


def test_complaint_endpoint_requires_server_identity_and_does_not_accept_citizen_id():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
            evidence_verifier=AcceptedEvidenceFixture(),
        )
    )

    response = client.post(
        "/api/v1/complaints",
        headers={"Idempotency-Key": "create-unauthenticated"},
        json={**_request_body(), "citizen_id": "attacker-controlled"},
    )

    assert response.status_code == 401


def test_complaint_endpoint_uses_authenticated_principal():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-2", identity_verified=True)
    client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
            principal_resolver=lambda _: principal,
            evidence_verifier=AcceptedEvidenceFixture(),
        )
    )

    response = client.post(
        "/api/v1/complaints",
        headers={"Authorization": "Bearer test-token", "Idempotency-Key": "create-2"},
        json=_request_body(),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "received"
    assert response.json()["execution_zone_state"] == "mapping_in_progress"
