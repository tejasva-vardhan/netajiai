from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.application.evidence import (
    CaptureAttestation,
    EvidenceAsset,
    EvidenceCaptureRejected,
    EvidenceIdempotencyConflict,
    EvidenceMetadataRepository,
    EvidenceUploadCleanupService,
    EvidenceUploadService,
    LocationMetadata,
    StoredObject,
)
from backend.app.application.complaints import EvidenceVerificationRequest
from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.contracts.evidence import (
    CompleteEvidencePartRequest,
    CreateEvidenceUploadRequest,
)
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import Base, EvidenceAssetRecord
from backend.app.infrastructure.evidence import SqlAlchemyEvidenceVerifier
from backend.app.infrastructure.evidence_capture import (
    FixtureCaptureAttestationVerifier,
    MetadataInspectionFixture,
    ReviewRequiredInspectionFixture,
)
from backend.app.infrastructure.evidence_repositories import (
    SqlAlchemyEvidenceMetadataRepository,
)
from backend.app.infrastructure.storage import InMemoryObjectStore


def _engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _photo_request(sha256: str = "a" * 64) -> CreateEvidenceUploadRequest:
    return CreateEvidenceUploadRequest(
        asset_type="photo",
        content_type="image/jpeg",
        byte_size=128,
        client_sha256=sha256,
        capture_attestation="fixture:native:camera-1",
        location={
            "latitude": 23.2599,
            "longitude": 77.4126,
            "accuracy_m": 12.5,
            "source": "device_gps",
        },
    )


def test_evidence_upload_is_direct_to_storage_and_verifies_server_metadata():
    engine = _engine()
    Base.metadata.create_all(engine)
    store = InMemoryObjectStore()
    principal = AuthenticatedPrincipal("digilocker:citizen-evidence", identity_verified=True)

    with Session(engine) as session:
        repository = SqlAlchemyEvidenceMetadataRepository(session)
        service = EvidenceUploadService(
            repository,
            FixtureCaptureAttestationVerifier(),
            store,
            MetadataInspectionFixture(),
        )
        response = service.create_upload(
            principal,
            _photo_request(),
            idempotency_key="upload-1",
        )
        assert response.status == "upload_pending"
        assert response.upload_url is not None
        asset = repository.find_by_creation_key(principal.subject_ref, "upload-1")
        assert asset is not None

        store.seed(
            StoredObject(
                object_key=asset.object_key,
                content_type="image/jpeg",
                byte_size=128,
                sha256="a" * 64,
            )
        )
        completed = service.complete_upload(principal, asset.evidence_asset_id)

        assert completed.status == "verified"
        verifier = SqlAlchemyEvidenceVerifier(session)
        decision = verifier.verify(
            principal,
            EvidenceVerificationRequest(
                evidence_asset_ids=(asset.evidence_asset_id,),
                issue_type="general",
                citizen_confirmation=True,
            ),
        )
        assert decision.accepted is True


def test_evidence_upload_rejects_reuse_of_key_with_different_metadata():
    engine = _engine()
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-evidence-conflict", identity_verified=True)

    with Session(engine) as session:
        service = EvidenceUploadService(
            SqlAlchemyEvidenceMetadataRepository(session),
            FixtureCaptureAttestationVerifier(),
            InMemoryObjectStore(),
            MetadataInspectionFixture(),
        )
        service.create_upload(principal, _photo_request(), idempotency_key="same-upload-key")
        with pytest.raises(EvidenceIdempotencyConflict, match="belongs to another request"):
            service.create_upload(
                principal,
                _photo_request("f" * 64),
                idempotency_key="same-upload-key",
            )


def test_evidence_repository_recovers_from_duplicate_key_during_commit():
    engine = _engine()
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-evidence-race", identity_verified=True)
    request = _photo_request()
    attestation = CaptureAttestation(
        capture_source="native_camera",
        device_captured_at=datetime.now(timezone.utc),
        attestation_hash="a" * 64,
    )
    location = LocationMetadata(
        latitude=23.2599,
        longitude=77.4126,
        accuracy_m=12.5,
        source="device_gps",
        captured_at=attestation.device_captured_at,
    )
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        repository = SqlAlchemyEvidenceMetadataRepository(session)
        winner = repository.create_pending(
            evidence_asset_id=uuid4(),
            citizen_id=principal.subject_ref,
            creation_idempotency_key="race-upload-1",
            request_fingerprint="request-fingerprint-1",
            request=request,
            object_key="evidence/winner",
            attestation=attestation,
            location=location,
            now=now,
        )
        retry = repository.create_pending(
            evidence_asset_id=uuid4(),
            citizen_id=principal.subject_ref,
            creation_idempotency_key="race-upload-1",
            request_fingerprint="request-fingerprint-1",
            request=request,
            object_key="evidence/loser",
            attestation=attestation,
            location=location,
            now=now,
        )

        assert retry.evidence_asset_id == winner.evidence_asset_id
        with pytest.raises(EvidenceIdempotencyConflict, match="belongs to another request"):
            repository.create_pending(
                evidence_asset_id=uuid4(),
                citizen_id=principal.subject_ref,
                creation_idempotency_key="race-upload-1",
                request_fingerprint="different-fingerprint",
                request=request,
                object_key="evidence/conflict",
                attestation=attestation,
                location=location,
                now=now,
            )


def test_evidence_upload_race_returns_a_grant_for_the_persisted_asset():
    principal = AuthenticatedPrincipal("digilocker:citizen-evidence-race-response", identity_verified=True)
    request = _photo_request()
    existing = EvidenceAsset(
        evidence_asset_id=uuid4(),
        citizen_id=principal.subject_ref,
        asset_type="photo",
        content_type="image/jpeg",
        byte_size=128,
        client_sha256="a" * 64,
        object_key="evidence/persisted",
        status="upload_pending",
        capture_source="native_camera",
        device_captured_at=datetime.now(timezone.utc),
        location_sample_id=None,
    )

    class RaceRepository:
        def find_by_creation_key(self, citizen_id: str, idempotency_key: str):
            del citizen_id, idempotency_key
            return None

        def create_pending(self, **kwargs):
            del kwargs
            return existing

    service = EvidenceUploadService(
        cast(EvidenceMetadataRepository, RaceRepository()),
        FixtureCaptureAttestationVerifier(),
        InMemoryObjectStore(),
        MetadataInspectionFixture(),
    )

    response = service.create_upload(principal, request, idempotency_key="race-upload-2")

    assert response.evidence_asset_id == existing.evidence_asset_id
    assert response.upload_url == "memory://evidence/persisted"


def test_tampered_object_is_rejected_before_complaint_submission():
    engine = _engine()
    Base.metadata.create_all(engine)
    store = InMemoryObjectStore()
    principal = AuthenticatedPrincipal("digilocker:citizen-tamper", identity_verified=True)

    with Session(engine) as session:
        repository = SqlAlchemyEvidenceMetadataRepository(session)
        service = EvidenceUploadService(
            repository,
            FixtureCaptureAttestationVerifier(),
            store,
            MetadataInspectionFixture(),
        )
        service.create_upload(principal, _photo_request(), idempotency_key="upload-tamper")
        asset = repository.find_by_creation_key(principal.subject_ref, "upload-tamper")
        assert asset is not None
        store.seed(
            StoredObject(
                object_key=asset.object_key,
                content_type="image/jpeg",
                byte_size=128,
                sha256="b" * 64,
            )
        )

        completed = service.complete_upload(principal, asset.evidence_asset_id)

        assert completed.status == "rejected"
        assert completed.reason_codes == ("object_integrity_mismatch",)


def test_large_evidence_upload_resumes_parts_and_completes_once():
    engine = _engine()
    Base.metadata.create_all(engine)
    store = InMemoryObjectStore()
    principal = AuthenticatedPrincipal("digilocker:citizen-multipart", identity_verified=True)
    byte_size = 10 * 1024 * 1024
    request = _photo_request("b" * 64).model_copy(update={"byte_size": byte_size})

    with Session(engine) as session:
        repository = SqlAlchemyEvidenceMetadataRepository(session)
        service = EvidenceUploadService(
            repository,
            FixtureCaptureAttestationVerifier(),
            store,
            MetadataInspectionFixture(),
        )
        response = service.create_upload(
            principal,
            request,
            idempotency_key="upload-multipart-1",
        )
        assert response.upload_mode == "multipart"
        assert response.part_count == 2
        assert len(response.parts) == 2
        asset = repository.find_by_creation_key(
            principal.subject_ref, "upload-multipart-1"
        )
        assert asset is not None

        incomplete = service.complete_upload(principal, asset.evidence_asset_id)
        assert incomplete.status == "uploaded"
        assert incomplete.reason_codes == ("multipart_parts_incomplete",)

        for part_number in (1, 2):
            part = service.complete_part(
                principal,
                asset.evidence_asset_id,
                part_number,
                CompleteEvidencePartRequest(
                    etag=f"etag-{part_number}",
                    sha256="c" * 64,
                    byte_size=5 * 1024 * 1024,
                ),
            )
            assert part.accepted is True
        with pytest.raises(EvidenceCaptureRejected, match="conflicts"):
            service.complete_part(
                principal,
                asset.evidence_asset_id,
                1,
                CompleteEvidencePartRequest(
                    etag="different-etag",
                    sha256="c" * 64,
                    byte_size=5 * 1024 * 1024,
                ),
            )
        retry = service.complete_part(
            principal,
            asset.evidence_asset_id,
            1,
            CompleteEvidencePartRequest(
                etag="etag-1",
                sha256="c" * 64,
                byte_size=5 * 1024 * 1024,
            ),
        )
        assert retry.accepted is True

        completed = service.complete_upload(principal, asset.evidence_asset_id)

        assert completed.status == "verified"
        assert len(store.multipart_completions) == 1


def test_abandoned_multipart_cleanup_claims_stale_sessions_and_preserves_active_uploads():
    engine = _engine()
    Base.metadata.create_all(engine)
    store = InMemoryObjectStore()
    principal = AuthenticatedPrincipal("digilocker:citizen-cleanup", identity_verified=True)
    byte_size = 10 * 1024 * 1024
    request = _photo_request("d" * 64).model_copy(update={"byte_size": byte_size})
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

    with Session(engine) as session:
        repository = SqlAlchemyEvidenceMetadataRepository(session)
        service = EvidenceUploadService(
            repository,
            FixtureCaptureAttestationVerifier(),
            store,
            MetadataInspectionFixture(),
        )
        service.create_upload(principal, request, idempotency_key="cleanup-old")
        service.create_upload(principal, request, idempotency_key="cleanup-active")
        old = repository.find_by_creation_key(principal.subject_ref, "cleanup-old")
        active = repository.find_by_creation_key(principal.subject_ref, "cleanup-active")
        assert old is not None and active is not None
        stale_record = session.get(EvidenceAssetRecord, old.evidence_asset_id)
        assert stale_record is not None
        stale_record.created_at = now - timedelta(days=2)
        stale_record.updated_at = stale_record.created_at
        session.commit()

        cleanup = EvidenceUploadCleanupService(repository, store)
        result = cleanup.cleanup_abandoned(
            now=now,
            max_age_seconds=24 * 60 * 60,
            retry_after_seconds=15 * 60,
            limit=10,
        )

        assert result.claimed == 1
        assert result.cleaned == 1
        assert result.failed == 0
        refreshed_old = repository.find_owned(principal.subject_ref, old.evidence_asset_id)
        refreshed_active = repository.find_owned(principal.subject_ref, active.evidence_asset_id)
        assert refreshed_old is not None and refreshed_old.status == "rejected"
        assert refreshed_active is not None and refreshed_active.status == "upload_pending"
        assert len(store.multipart_aborts) == 1


def test_abandoned_multipart_cleanup_retries_a_transient_abort_failure():
    class FlakyStore(InMemoryObjectStore):
        def __init__(self) -> None:
            super().__init__()
            self.failures_remaining = 1

        def abort_multipart_upload(self, *, object_key: str, upload_id: str) -> None:
            if self.failures_remaining:
                self.failures_remaining -= 1
                raise RuntimeError("temporary storage failure")
            super().abort_multipart_upload(object_key=object_key, upload_id=upload_id)

    engine = _engine()
    Base.metadata.create_all(engine)
    store = FlakyStore()
    principal = AuthenticatedPrincipal("digilocker:citizen-cleanup-retry", identity_verified=True)
    request = _photo_request("e" * 64).model_copy(update={"byte_size": 10 * 1024 * 1024})
    first_now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

    with Session(engine) as session:
        repository = SqlAlchemyEvidenceMetadataRepository(session)
        upload_service = EvidenceUploadService(
            repository,
            FixtureCaptureAttestationVerifier(),
            store,
            MetadataInspectionFixture(),
        )
        upload_service.create_upload(principal, request, idempotency_key="cleanup-retry")
        asset = repository.find_by_creation_key(principal.subject_ref, "cleanup-retry")
        assert asset is not None
        record = session.get(EvidenceAssetRecord, asset.evidence_asset_id)
        assert record is not None
        record.created_at = first_now - timedelta(days=2)
        record.updated_at = record.created_at
        session.commit()

        cleanup = EvidenceUploadCleanupService(repository, store)
        failed = cleanup.cleanup_abandoned(
            now=first_now,
            max_age_seconds=86_400,
            retry_after_seconds=900,
            limit=10,
        )
        assert failed.claimed == 1 and failed.failed == 1
        pending = repository.find_owned(principal.subject_ref, asset.evidence_asset_id)
        assert pending is not None and pending.status == "upload_pending"

        completed = cleanup.cleanup_abandoned(
            now=first_now + timedelta(minutes=16),
            max_age_seconds=86_400,
            retry_after_seconds=900,
            limit=10,
        )
        assert completed.claimed == 1 and completed.cleaned == 1
        rejected = repository.find_owned(principal.subject_ref, asset.evidence_asset_id)
        assert rejected is not None and rejected.status == "rejected"
        assert store.multipart_aborts == [store.multipart_sessions[asset.object_key].upload_id]


def test_verified_photo_requires_location_and_native_capture():
    engine = _engine()
    Base.metadata.create_all(engine)
    principal = AuthenticatedPrincipal("digilocker:citizen-policy", identity_verified=True)

    with Session(engine) as session:
        service = EvidenceUploadService(
            SqlAlchemyEvidenceMetadataRepository(session),
            FixtureCaptureAttestationVerifier(),
            InMemoryObjectStore(),
            MetadataInspectionFixture(),
        )
        without_location = _photo_request().model_copy(update={"location": None})
        with pytest.raises(EvidenceCaptureRejected, match="captured location"):
            service.create_upload(principal, without_location, idempotency_key="no-location")

        gallery_token = _photo_request().model_copy(
            update={"capture_attestation": "gallery:file-1"}
        )
        with pytest.raises(ValueError, match="Unsupported capture attestation"):
            service.create_upload(principal, gallery_token, idempotency_key="gallery")


def test_evidence_http_contract_uses_authenticated_identity_and_presigned_flow():
    engine = _engine()
    Base.metadata.create_all(engine)
    store = InMemoryObjectStore()
    principal = AuthenticatedPrincipal("digilocker:citizen-http", identity_verified=True)
    client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
            principal_resolver=lambda _: principal,
            capture_verifier=FixtureCaptureAttestationVerifier(),
            object_store=store,
            media_inspector=MetadataInspectionFixture(),
        )
    )

    response = client.post(
        "/api/v1/evidence/uploads",
        headers={"Authorization": "Bearer test", "Idempotency-Key": "http-upload-1"},
        json=_photo_request().model_dump(mode="json"),
    )

    assert response.status_code == 201
    evidence_asset_id = response.json()["evidence_asset_id"]
    with Session(engine) as session:
        asset = SqlAlchemyEvidenceMetadataRepository(session).find_owned(
            principal.subject_ref, UUID(evidence_asset_id)
        )
    assert asset is not None
    store.seed(
        StoredObject(
            object_key=asset.object_key,
            content_type="image/jpeg",
            byte_size=128,
            sha256="a" * 64,
        )
    )

    completed = client.post(
        f"/api/v1/evidence/{evidence_asset_id}/complete",
        headers={"Authorization": "Bearer test"},
    )

    assert completed.status_code == 200
    assert completed.json()["status"] == "verified"

    complaint = client.post(
        "/api/v1/complaints",
        headers={"Authorization": "Bearer test", "Idempotency-Key": "complaint-http-1"},
        json={
            "issue_type": "general",
            "description": "The public tap is not working.",
            "language": "hi-en",
            "evidence_asset_ids": [evidence_asset_id],
            "citizen_confirmation": True,
        },
    )

    assert complaint.status_code == 201
    assert complaint.json()["status"] == "received"
    complaint_id = complaint.json()["complaint_id"]

    tracking = client.get(
        f"/api/v1/complaints/{complaint_id}",
        headers={"Authorization": "Bearer test"},
    )
    assert tracking.status_code == 200
    assert tracking.json()["description"] == "The public tap is not working."

    other_client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                "digilocker:other-citizen", identity_verified=True
            ),
        )
    )
    not_owned = other_client.get(
        f"/api/v1/complaints/{complaint_id}",
        headers={"Authorization": "Bearer other"},
    )
    assert not_owned.status_code == 404

    citizen_transition = client.post(
        f"/api/v1/complaints/{complaint_id}/transitions",
        headers={"Authorization": "Bearer test", "Idempotency-Key": "citizen-transition"},
        json={"to_status": "verifying"},
    )
    assert citizen_transition.status_code == 403

    workflow_client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                "workflow-worker",
                roles=frozenset({"workflow"}),
                identity_verified=True,
            ),
        )
    )
    transitioned = workflow_client.post(
        f"/api/v1/complaints/{complaint_id}/transitions",
        headers={"Authorization": "Bearer workflow", "Idempotency-Key": "transition-1"},
        json={"to_status": "verifying"},
    )
    assert transitioned.status_code == 200
    assert transitioned.json()["status"] == "verifying"
    assert transitioned.json()["version"] == 2

    retry = workflow_client.post(
        f"/api/v1/complaints/{complaint_id}/transitions",
        headers={"Authorization": "Bearer workflow", "Idempotency-Key": "transition-1"},
        json={"to_status": "verifying"},
    )
    assert retry.status_code == 200
    assert retry.json()["version"] == 2

    invalid = workflow_client.post(
        f"/api/v1/complaints/{complaint_id}/transitions",
        headers={"Authorization": "Bearer workflow", "Idempotency-Key": "transition-2"},
        json={"to_status": "closed"},
    )
    assert invalid.status_code == 422


def test_uncertain_media_enters_operator_review_queue_and_is_idempotently_approved():
    engine = _engine()
    Base.metadata.create_all(engine)
    store = InMemoryObjectStore()
    citizen = AuthenticatedPrincipal("digilocker:review-citizen", identity_verified=True)
    with Session(engine) as session:
        upload_service = EvidenceUploadService(
            SqlAlchemyEvidenceMetadataRepository(session),
            FixtureCaptureAttestationVerifier(),
            store,
            ReviewRequiredInspectionFixture(),
        )
        upload_service.create_upload(citizen, _photo_request(), idempotency_key="review-upload")
        asset = SqlAlchemyEvidenceMetadataRepository(session).find_by_creation_key(
            citizen.subject_ref, "review-upload"
        )
        assert asset is not None
        store.seed(
            StoredObject(
                object_key=asset.object_key,
                content_type="image/jpeg",
                byte_size=128,
                sha256="a" * 64,
            )
        )
        completed = upload_service.complete_upload(citizen, asset.evidence_asset_id)
        assert completed.status == "review_required"
        repeated = upload_service.complete_upload(citizen, asset.evidence_asset_id)
        assert repeated.status == "review_required"
        assert repeated.reason_codes == ("clarity_uncertain",)

    def resolve_principal(authorization: str) -> AuthenticatedPrincipal:
        if "operator" in authorization:
            return AuthenticatedPrincipal("operator:media-review", roles=frozenset({"operator"}))
        return citizen

    app = create_app(
        Settings(environment="test"),
        session_factory=lambda: Session(engine),
        principal_resolver=resolve_principal,
        object_store=store,
    )
    client = TestClient(app)
    citizen_queue = client.get(
        "/api/v1/admin/evidence/review-queue",
        headers={"Authorization": "Bearer citizen"},
    )
    assert citizen_queue.status_code == 403
    queue = client.get(
        "/api/v1/admin/evidence/review-queue",
        headers={"Authorization": "Bearer operator"},
    )
    assert queue.status_code == 200
    item = queue.json()["items"][0]
    assert item["evidence_asset_id"] == str(asset.evidence_asset_id)
    assert item["reason_codes"] == ["clarity_uncertain"]
    assert "citizen_id" not in item
    assert "object_key" not in item
    assert item["preview_url"].startswith("memory://preview/")

    decision_headers = {
        "Authorization": "Bearer operator",
        "Idempotency-Key": "review-decision-1",
    }
    decision = client.post(
        f"/api/v1/admin/evidence/{asset.evidence_asset_id}/review",
        headers=decision_headers,
        json={"decision": "approve", "reason_code": "human_confirmed"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "verified"

    replay = client.post(
        f"/api/v1/admin/evidence/{asset.evidence_asset_id}/review",
        headers=decision_headers,
        json={"decision": "approve", "reason_code": "human_confirmed"},
    )
    assert replay.status_code == 200
    assert replay.json() == decision.json()

    conflicting_replay = client.post(
        f"/api/v1/admin/evidence/{asset.evidence_asset_id}/review",
        headers=decision_headers,
        json={"decision": "reject", "reason_code": "operator_rejected"},
    )
    assert conflicting_replay.status_code == 409

    empty_queue = client.get(
        "/api/v1/admin/evidence/review-queue",
        headers={"Authorization": "Bearer operator"},
    )
    assert empty_queue.status_code == 200
    assert empty_queue.json()["items"] == []

    with Session(engine) as session:
        upload_service = EvidenceUploadService(
            SqlAlchemyEvidenceMetadataRepository(session),
            FixtureCaptureAttestationVerifier(),
            store,
            ReviewRequiredInspectionFixture(),
        )
        upload_service.create_upload(
            citizen, _photo_request(), idempotency_key="review-upload-reject"
        )
        rejected_asset = SqlAlchemyEvidenceMetadataRepository(session).find_by_creation_key(
            citizen.subject_ref, "review-upload-reject"
        )
        assert rejected_asset is not None
        store.seed(
            StoredObject(
                object_key=rejected_asset.object_key,
                content_type="image/jpeg",
                byte_size=128,
                sha256="a" * 64,
            )
        )
        rejected_upload = upload_service.complete_upload(citizen, rejected_asset.evidence_asset_id)
        assert rejected_upload.status == "review_required"

    rejection = client.post(
        f"/api/v1/admin/evidence/{rejected_asset.evidence_asset_id}/review",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "review-reject-1"},
        json={"decision": "reject", "reason_code": "not_civic_evidence"},
    )
    assert rejection.status_code == 200
    assert rejection.json()["status"] == "rejected"
