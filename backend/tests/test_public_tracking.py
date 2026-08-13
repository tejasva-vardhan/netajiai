from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.db import Base
from backend.app.infrastructure.evidence import AcceptedEvidenceFixture
from backend.app.infrastructure.tracking import HmacPublicTrackingTokenCodec


def _body() -> dict:
    return {
        "issue_type": "streetlight",
        "description": "A detailed private description that must not be public.",
        "language": "hi-en",
        "jurisdiction_code": "IN-TEST-001",
        "evidence_asset_ids": [str(uuid4())],
        "citizen_confirmation": True,
    }


def test_public_tracking_uses_signed_capability_and_redacts_citizen_data():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    codec = HmacPublicTrackingTokenCodec("t" * 32)
    client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                subject_ref="oidc:citizen-public", identity_verified=True
            ),
            evidence_verifier=AcceptedEvidenceFixture(),
            tracking_token_codec=codec,
        )
    )

    created = client.post(
        "/api/v1/complaints",
        headers={"Authorization": "Bearer test", "Idempotency-Key": "public-1"},
        json=_body(),
    )
    token = created.json()["tracking_token"]
    public = client.get(f"/api/v1/public/complaints/{token}")

    assert created.status_code == 201
    assert token
    assert public.status_code == 200
    assert set(public.json()) == {
        "complaint_id",
        "status",
        "version",
        "issue_type",
        "execution_zone_state",
        "escalation_level",
        "created_at",
        "updated_at",
    }
    assert "description" not in public.json()
    assert "IN-TEST-001" not in public.text

    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert client.get(f"/api/v1/public/complaints/{tampered}").status_code == 404


def test_tracking_codec_rejects_wrong_secret_and_malformed_tokens():
    complaint_id = uuid4()
    codec = HmacPublicTrackingTokenCodec("s" * 32)
    token = codec.encode(complaint_id)

    assert codec.decode(token) == complaint_id
    assert HmacPublicTrackingTokenCodec("x" * 32).decode(token) is None
    assert codec.decode("not-a-token") is None
