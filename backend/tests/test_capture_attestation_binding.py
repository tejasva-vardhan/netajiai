from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.application.evidence import (
    CaptureAttestation,
    CaptureAttestationVerifier,
    EvidenceUploadService,
)
from backend.app.contracts.evidence import CreateEvidenceUploadRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import Base
from backend.app.infrastructure.evidence_capture import MetadataInspectionFixture
from backend.app.infrastructure.evidence_repositories import SqlAlchemyEvidenceMetadataRepository
from backend.app.infrastructure.storage import InMemoryObjectStore


class _BindingVerifier:
    def __init__(self) -> None:
        self.received: tuple[str, str, str, str] | None = None

    def verify(
        self, token: str, asset_type: str, citizen_id: str, idempotency_key: str
    ) -> CaptureAttestation:
        self.received = (token, asset_type, citizen_id, idempotency_key)
        return CaptureAttestation(
            capture_source="native_camera",
            device_captured_at=datetime.now(timezone.utc),
            attestation_hash="a" * 64,
        )


def test_capture_attestation_port_requires_authenticated_subject_binding() -> None:
    verifier: CaptureAttestationVerifier = _BindingVerifier()
    result = verifier.verify("token", "photo", "citizen-1", "capture-1")

    assert result.capture_source == "native_camera"
    assert isinstance(verifier, _BindingVerifier)
    assert verifier.received == ("token", "photo", "citizen-1", "capture-1")


def test_evidence_service_passes_server_authenticated_subject_to_verifier() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    verifier = _BindingVerifier()
    request = CreateEvidenceUploadRequest(
        asset_type="photo",
        content_type="image/jpeg",
        byte_size=128,
        client_sha256="a" * 64,
        capture_attestation="token",
        location={
            "latitude": 23.2599,
            "longitude": 77.4126,
            "accuracy_m": 12.5,
            "source": "device_gps",
        },
    )
    principal = AuthenticatedPrincipal("citizen-bound", identity_verified=True)

    with Session(engine) as session:
        service = EvidenceUploadService(
            SqlAlchemyEvidenceMetadataRepository(session),
            verifier,
            InMemoryObjectStore(),
            MetadataInspectionFixture(),
        )
        response = service.create_upload(principal, request, idempotency_key="binding-1")

    assert response.status == "upload_pending"
    assert verifier.received == ("token", "photo", "citizen-bound", "binding-1")
