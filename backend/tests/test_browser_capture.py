import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.main import create_app
from backend.app.application.evidence import (
    EvidenceUploadService,
    InspectionResult,
    StoredObject,
)
from backend.app.config import Settings
from backend.app.contracts.evidence import CreateEvidenceUploadRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.browser_capture import (
    BrowserCaptureSessionError,
    BrowserCaptureSessionSigner,
)
from backend.app.infrastructure.db import Base
from backend.app.infrastructure.evidence_repositories import (
    SqlAlchemyEvidenceMetadataRepository,
)
from backend.app.infrastructure.storage import InMemoryObjectStore


SECRET = "browser-capture-test-secret-with-32-bytes"


class _AcceptedInspector:
    def inspect(self, stored_object: StoredObject, asset: object) -> InspectionResult:
        del stored_object, asset
        return InspectionResult(accepted=True)


def test_browser_session_is_bound_to_subject_asset_and_idempotency_key() -> None:
    signer = BrowserCaptureSessionSigner(SECRET)
    session = signer.issue(
        citizen_id="citizen-1",
        asset_type="photo",
        idempotency_key="capture-photo-1",
    )

    attestation = signer.verify(
        session.token,
        "photo",
        "citizen-1",
        "capture-photo-1",
    )

    assert attestation.capture_source == "browser_camera"
    with pytest.raises(BrowserCaptureSessionError):
        signer.verify(session.token, "photo", "citizen-2", "capture-photo-1")
    with pytest.raises(BrowserCaptureSessionError):
        signer.verify(session.token, "audio", "citizen-1", "capture-photo-1")
    with pytest.raises(BrowserCaptureSessionError):
        signer.verify(session.token, "photo", "citizen-1", "capture-photo-2")
    with pytest.raises(BrowserCaptureSessionError):
        replacement = "A" if session.token[-1] != "A" else "B"
        signer.verify(
            session.token[:-1] + replacement,
            "photo",
            "citizen-1",
            "capture-photo-1",
        )


def test_browser_capture_is_review_gated_even_when_media_inspector_accepts() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    signer = BrowserCaptureSessionSigner(SECRET)
    principal = AuthenticatedPrincipal("browser-citizen", identity_verified=True)
    idempotency_key = "browser-photo-1"
    session = signer.issue(
        citizen_id=principal.subject_ref,
        asset_type="photo",
        idempotency_key=idempotency_key,
    )
    request = CreateEvidenceUploadRequest(
        asset_type="photo",
        content_type="image/jpeg",
        byte_size=128,
        client_sha256="a" * 64,
        capture_attestation=session.token,
        location={
            "latitude": 23.2599,
            "longitude": 77.4126,
            "accuracy_m": 12.5,
            "source": "browser_gps",
        },
    )
    store = InMemoryObjectStore()

    with Session(engine) as db_session:
        repository = SqlAlchemyEvidenceMetadataRepository(db_session)
        service = EvidenceUploadService(repository, signer, store, _AcceptedInspector())
        upload = service.create_upload(
            principal,
            request,
            idempotency_key=idempotency_key,
        )
        asset = repository.find_owned(principal.subject_ref, upload.evidence_asset_id)
        assert asset is not None
        store.seed(
            StoredObject(
                object_key=asset.object_key,
                content_type="image/jpeg",
                byte_size=128,
                sha256="a" * 64,
            )
        )
        completed = service.complete_upload(principal, upload.evidence_asset_id)

    assert completed.status == "review_required"
    assert "browser_capture_review" in completed.reason_codes


def test_browser_capture_session_endpoint_requires_explicit_enablement() -> None:
    signer = BrowserCaptureSessionSigner(SECRET)
    app = create_app(
        Settings(environment="test", web_capture_enabled=True),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "browser-api-citizen", identity_verified=True
        ),
        capture_session_issuer=signer,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/evidence/capture-sessions",
        headers={
            "Authorization": "Bearer test-token",
            "Idempotency-Key": "browser-api-photo-1",
        },
        json={"asset_type": "photo"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["capture_token"]
    assert body["expires_at"]
