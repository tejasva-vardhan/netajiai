from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.application.complaints import ComplaintSubmissionService
from backend.app.application.issue_clusters import IssueClusterPolicy
from backend.app.contracts.complaints import CreateComplaintRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import (
    Base,
    ComplaintRecord,
    EvidenceAssetRecord,
    IssueClusterMemberRecord,
    IssueClusterRecord,
    LocationSampleRecord,
    OutboxMessage,
)
from backend.app.infrastructure.evidence import AcceptedEvidenceFixture
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository


KEY = "test-issue-cluster-key-with-at-least-32-bytes"
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def test_policy_is_deterministic_and_rejects_low_accuracy_location():
    policy = IssueClusterPolicy(hmac_key=KEY)
    common = {
        "issue_type": "  Pothole  ",
        "latitude": 23.2599,
        "longitude": 77.4126,
        "accuracy_m": 40,
        "captured_at": NOW,
        "supporter_ref": "digilocker:citizen-1",
    }

    first = policy.candidate(**common)
    second = policy.candidate(**{**common, "issue_type": "pothole"})

    assert first is not None
    assert first == second
    assert first.normalized_issue_type == "pothole"
    assert policy.candidate(**{**common, "accuracy_m": 101}) is None
    assert policy.candidate(**{**common, "supporter_ref": "digilocker:citizen-2"}).supporter_ref_hash != first.supporter_ref_hash
    shifted = policy.candidate(
        **{**common, "captured_at": NOW + timedelta(hours=73)}
    )
    assert shifted is not None
    assert first.cluster_key != shifted.cluster_key


def test_verified_server_location_creates_non_destructive_cluster_and_distinct_count():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    policy = IssueClusterPolicy(hmac_key=KEY)
    principal_one = AuthenticatedPrincipal("digilocker:citizen-1", identity_verified=True)
    principal_two = AuthenticatedPrincipal("digilocker:citizen-2", identity_verified=True)

    def add_verified_evidence(session: Session, principal: AuthenticatedPrincipal) -> object:
        evidence_id = uuid4()
        location = LocationSampleRecord(
            citizen_id=principal.subject_ref,
            latitude=23.2599,
            longitude=77.4126,
            accuracy_m=40,
            source="native_gps",
            captured_at=NOW,
            server_received_at=NOW,
        )
        session.add(location)
        session.flush()
        session.add(
            EvidenceAssetRecord(
                id=evidence_id,
                citizen_id=principal.subject_ref,
                creation_idempotency_key=f"evidence-{evidence_id}",
                creation_request_fingerprint="f" * 64,
                asset_type="photo",
                content_type="image/jpeg",
                byte_size=100,
                client_sha256="a" * 64,
                object_key=f"evidence/{evidence_id}",
                status="verified",
                capture_source="native_camera",
                capture_attestation_hash="b" * 64,
                device_captured_at=NOW,
                server_received_at=NOW,
                verified_at=NOW,
                verification_signals={"reason_codes": []},
                location_sample_id=location.id,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        return evidence_id

    def create(
        session: Session,
        principal: AuthenticatedPrincipal,
        idempotency_key: str,
        description: str,
    ):
        evidence_id = add_verified_evidence(session, principal)
        service = ComplaintSubmissionService(
            SqlAlchemyComplaintSubmissionRepository(
                session, issue_cluster_policy=policy
            ),
            AcceptedEvidenceFixture(),
        )
        return service.create(
            principal,
            CreateComplaintRequest(
                issue_type="pothole",
                description=description,
                language="hi-en",
                evidence_asset_ids=[evidence_id],
                citizen_confirmation=True,
            ),
            idempotency_key=idempotency_key,
            correlation_id=f"correlation-{idempotency_key}",
        )

    with Session(engine) as session:
        first = create(session, principal_one, "complaint-1", "Pothole near the school")
        second = create(session, principal_two, "complaint-2", "Same pothole blocks traffic")
        third = create(session, principal_one, "complaint-3", "Pothole still open")

        assert first.issue_cluster_id is not None
        assert first.supporter_count == 1
        assert second.issue_cluster_id == first.issue_cluster_id
        assert second.supporter_count == 2
        assert third.issue_cluster_id == first.issue_cluster_id
        assert third.supporter_count == 2

        first_tracking = SqlAlchemyComplaintSubmissionRepository(session).find_owned(
            principal_one.subject_ref, first.complaint_id
        )
        assert first_tracking is not None
        assert first_tracking.issue_cluster_id == first.issue_cluster_id
        assert first_tracking.supporter_count == 2

        records = list(session.scalars(select(ComplaintRecord).order_by(ComplaintRecord.created_at)))
        assert len(records) == 3
        assert {record.status for record in records} == {"received"}
        assert {record.issue_cluster_supporter_count for record in records} == {2}
        clusters = list(session.scalars(select(IssueClusterRecord)))
        members = list(session.scalars(select(IssueClusterMemberRecord)))
        assert len(clusters) == 1
        assert clusters[0].supporter_count == 2
        assert len(members) == 3
        assert not hasattr(clusters[0], "latitude")

        lifecycle_messages = list(session.scalars(select(OutboxMessage)))
        assert lifecycle_messages[0].payload["issue_cluster_id"] == str(first.issue_cluster_id)
        assert lifecycle_messages[1].payload["issue_cluster_supporter_count"] == 2
