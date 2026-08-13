from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.main import create_app
from backend.app.application.routing import RoutingDecision
from backend.app.config import Settings
from backend.app.contracts.complaints import CreateComplaintRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.domain.complaints import ComplaintAggregate
from backend.app.infrastructure.db import (
    Base,
    CitizenResolutionResponseRecord,
    ClosureProofClaimRecord,
    ComplaintEventRecord,
    ComplaintRecord,
    DepartmentReplyRecord,
)
from backend.app.infrastructure.closure import FixtureClosureProofVerifier
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository


class FakeWorkflowSignalSender:
    def __init__(self) -> None:
        self.department_calls: list[tuple[UUID, UUID, str]] = []
        self.confirmation_calls: list[tuple[UUID, UUID, str]] = []
        self.routing_calls: list[tuple[UUID, UUID]] = []

    async def routing_activation(self, complaint_id: UUID, *, signal_id: UUID) -> None:
        self.routing_calls.append((complaint_id, signal_id))

    async def department_response(
        self,
        complaint_id: UUID,
        *,
        signal_id: UUID,
        outcome: Literal["fix_reported", "no_resolution"],
        proof_claim_id: UUID | None,
    ) -> None:
        self.department_calls.append((complaint_id, signal_id, outcome))

    async def citizen_confirmation(
        self, complaint_id: UUID, *, signal_id: UUID, outcome: str
    ) -> None:
        self.confirmation_calls.append((complaint_id, signal_id, outcome))


class FakeRoutingActivationResolver:
    def resolve(self, complaint_id: UUID) -> RoutingDecision:
        del complaint_id
        return RoutingDecision(
            state="active",
            jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
            snapshot_ref="synthetic-mp-routing-v1",
            reason_code="synthetic_zone_match",
        )


def _engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _seed_complaint(
    engine, citizen_id: str, *, status: str = "received"
) -> UUID:
    complaint_id = uuid4()
    with Session(engine) as session:
        SqlAlchemyComplaintSubmissionRepository(session).persist_received(
            ComplaintAggregate.receive(
                complaint_id,
                actor_type="citizen",
                actor_id=citizen_id,
                policy_version="test.v1",
                correlation_id="test:signal",
                idempotency_key=f"create:{complaint_id}",
            ),
            CreateComplaintRequest(
                issue_type="pothole",
                description="A pothole needs repair.",
                language="en",
                jurisdiction_code="IN-SYNTHETIC",
                evidence_asset_ids=[uuid4()],
                citizen_confirmation=True,
            ),
            AuthenticatedPrincipal(citizen_id, identity_verified=True),
            RoutingDecision.mapping_in_progress(reason_code="test_fixture"),
        )
        if status != "received":
            record = session.get(ComplaintRecord, complaint_id)
            assert record is not None
            record.status = status
            session.commit()
    return complaint_id


def test_department_signal_is_capability_protected_and_idempotent():
    engine = _engine()
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine, "citizen:1")
    sender = FakeWorkflowSignalSender()
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "operator:1", roles=frozenset({"operator"})
        ),
        workflow_signal_sender=sender,
        closure_proof_verifier=FixtureClosureProofVerifier(),
    )
    client = TestClient(app)
    headers = {"Idempotency-Key": "department-response-1"}
    path = f"/api/v1/admin/complaints/{complaint_id}/department-response"

    proof = {
        "proof_type": "department_reference",
        "proof_reference": f"fixture:closure:{complaint_id}:work-order-1",
    }
    first = client.post(
        path,
        headers=headers,
        json={"outcome": "fix_reported", "proof": proof},
    )
    retry = client.post(
        path,
        headers=headers,
        json={"outcome": "fix_reported", "proof": proof},
    )
    conflict = client.post(path, headers=headers, json={"outcome": "no_resolution"})

    assert first.status_code == 202
    assert retry.status_code == 202
    assert retry.json() == first.json()
    assert conflict.status_code == 409
    assert len(sender.department_calls) == 1

    with Session(engine) as session:
        claims = list(
            session.query(ClosureProofClaimRecord).filter_by(complaint_id=complaint_id)
        )
        assert len(claims) == 1
        assert claims[0].status == "accepted"
        assert claims[0].proof_reference_hash != proof["proof_reference"]
        assert claims[0].submitted_by == "operator:1"

    missing_proof = client.post(
        path,
        headers={"Idempotency-Key": "department-response-missing-proof"},
        json={"outcome": "fix_reported"},
    )
    assert missing_proof.status_code == 422

    rejected_proof = client.post(
        path,
        headers={"Idempotency-Key": "department-response-rejected-proof"},
        json={
            "outcome": "fix_reported",
            "proof": {
                "proof_type": "department_reference",
                "proof_reference": "not-a-fixture",
            },
        },
    )
    assert rejected_proof.status_code == 422


def test_department_reply_is_private_idempotent_and_classified_without_changing_outcome():
    engine = _engine()
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine, "citizen:reply")
    sender = FakeWorkflowSignalSender()
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "operator:reply", roles=frozenset({"operator"})
        ),
        workflow_signal_sender=sender,
    )
    client = TestClient(app)
    path = f"/api/v1/admin/complaints/{complaint_id}/department-response"
    text = "The complaint is under process; action will be taken soon."

    first = client.post(
        path,
        headers={"Idempotency-Key": "reply-1"},
        json={"outcome": "no_resolution", "reply_text": text},
    )
    retry = client.post(
        path,
        headers={"Idempotency-Key": "reply-1"},
        json={"outcome": "no_resolution", "reply_text": text},
    )
    duplicate = client.post(
        path,
        headers={"Idempotency-Key": "reply-2"},
        json={"outcome": "no_resolution", "reply_text": text},
    )
    conflict = client.post(
        path,
        headers={"Idempotency-Key": "reply-1"},
        json={"outcome": "no_resolution", "reply_text": "A different reply"},
    )

    assert first.status_code == 202
    assert first.json()["reply_classification"] == "weak"
    assert first.json()["reply_id"]
    assert retry.status_code == 202
    assert retry.json() == first.json()
    assert duplicate.status_code == 202
    assert duplicate.json()["reply_classification"] == "duplicate"
    assert conflict.status_code == 409
    assert len(sender.department_calls) == 2

    with Session(engine) as session:
        replies = list(
            session.query(DepartmentReplyRecord).filter_by(complaint_id=complaint_id)
        )
        assert len(replies) == 2
        assert {reply.outcome for reply in replies} == {"no_resolution"}
        assert replies[0].response_text_hash
        assert "under process" in (replies[0].response_text or "")
        complaint = session.get(ComplaintRecord, complaint_id)
        assert complaint is not None
        assert complaint.status == "received"


def test_citizen_confirmation_is_owned_and_idempotent():
    engine = _engine()
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(
        engine, "citizen:1", status="awaiting_citizen_confirmation"
    )
    sender = FakeWorkflowSignalSender()
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal("citizen:1"),
        workflow_signal_sender=sender,
    )
    client = TestClient(app)
    path = f"/api/v1/complaints/{complaint_id}/citizen-confirmation"

    response = client.post(
        path,
        headers={"Idempotency-Key": "citizen-confirmation-1"},
        json={"outcome": "fully_solved"},
    )

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert len(sender.confirmation_calls) == 1

    other_app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal("citizen:other"),
        workflow_signal_sender=sender,
    )
    not_owner = TestClient(other_app).post(
        path,
        headers={"Idempotency-Key": "other-confirmation-1"},
        json={"outcome": "fully_solved"},
    )
    assert not_owner.status_code == 404


def test_citizen_confirmation_is_rejected_before_the_workflow_requests_it():
    engine = _engine()
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine, "citizen:1")
    sender = FakeWorkflowSignalSender()
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal("citizen:1"),
        workflow_signal_sender=sender,
    )

    response = TestClient(app).post(
        f"/api/v1/complaints/{complaint_id}/citizen-confirmation",
        headers={"Idempotency-Key": "early-confirmation-1"},
        json={"outcome": "fully_solved"},
    )

    assert response.status_code == 409
    assert sender.confirmation_calls == []


def test_partial_citizen_outcome_is_durable_and_conflicting_choice_is_rejected():
    engine = _engine()
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(
        engine, "citizen:1", status="awaiting_citizen_confirmation"
    )
    sender = FakeWorkflowSignalSender()
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal("citizen:1"),
        workflow_signal_sender=sender,
    )
    client = TestClient(app)
    path = f"/api/v1/complaints/{complaint_id}/citizen-confirmation"

    first = client.post(
        path,
        headers={"Idempotency-Key": "citizen-partial-1"},
        json={"outcome": "partially_solved"},
    )
    retry = client.post(
        path,
        headers={"Idempotency-Key": "citizen-partial-1"},
        json={"outcome": "partially_solved"},
    )
    conflict = client.post(
        path,
        headers={"Idempotency-Key": "citizen-not-solved-1"},
        json={"outcome": "not_solved"},
    )

    assert first.status_code == 202
    assert retry.status_code == 202
    assert retry.json() == first.json()
    assert conflict.status_code == 409
    assert len(sender.confirmation_calls) == 1
    with Session(engine) as session:
        response = session.query(CitizenResolutionResponseRecord).one()
        assert response.complaint_id == complaint_id
        assert response.outcome == "partially_solved"


def test_routing_activation_uses_server_owned_decision_and_retries_signal_only():
    engine = _engine()
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine, "citizen:1")
    sender = FakeWorkflowSignalSender()
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "operator:1", roles=frozenset({"operator"})
        ),
        routing_activation_resolver=FakeRoutingActivationResolver(),
        workflow_signal_sender=sender,
    )
    client = TestClient(app)
    path = f"/api/v1/admin/complaints/{complaint_id}/routing-activation"
    headers = {"Idempotency-Key": "routing-activation-1"}

    first = client.post(path, headers=headers, json={})
    retry = client.post(path, headers=headers, json={})
    second_activation = client.post(
        path,
        headers={"Idempotency-Key": "routing-activation-2"},
        json={},
    )

    assert first.status_code == 202
    assert retry.status_code == 202
    assert retry.json() == first.json()
    assert second_activation.status_code == 409
    assert len(sender.routing_calls) == 1

    with Session(engine) as session:
        record = session.get(ComplaintRecord, complaint_id)
        assert record is not None
        assert record.execution_zone_state == "active"
        assert record.jurisdiction_code == "IN-MP-SYNTHETIC-BHOPAL"
        assert record.routing_snapshot_ref == "synthetic-mp-routing-v1"
        events = list(
            session.query(ComplaintEventRecord)
            .filter_by(
                complaint_id=complaint_id,
                event_type="complaint.routing_activated",
            )
        )
        assert len(events) == 1
