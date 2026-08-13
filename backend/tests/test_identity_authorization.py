from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.api.dependencies import get_verified_principal
from backend.app.application.identity import (
    IdentityAuthorizationRejected,
    IdentityAuthorizationService,
    IdentityVerificationService,
)
from backend.app.contracts.identity import AuthenticatedPrincipal, IdentityVerificationResult
from backend.app.config import Settings
from backend.app.infrastructure.db import Base, IdentityAuthorizationStateRecord
from backend.app.infrastructure.identity import SandboxDigiLockerVerifier
from backend.app.infrastructure.identity_authorization import (
    FernetIdentityStateCipher,
    SqlAlchemyAuthorizationStateRepository,
)
from backend.app.infrastructure.identity_repositories import SqlAlchemyIdentityVerificationRepository


def test_expired_digilocker_record_overrides_stale_oidc_verified_claim():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    with Session(engine) as session:
        SqlAlchemyIdentityVerificationRepository(session).save(
            IdentityVerificationResult(
                subject_ref="oidc:expired-citizen",
                status="verified",
                provider="digilocker",
                method="requester_oauth",
                consent_id="expired-consent",
                expires_at=now - timedelta(seconds=1),
            ),
            reference_hash="e" * 64,
            retention_until=None,
            now=now - timedelta(minutes=5),
        )

    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
    )
    request = Request({"type": "http", "app": app})
    principal = get_verified_principal(
        request,
        AuthenticatedPrincipal("oidc:expired-citizen", identity_verified=True),
    )

    assert principal.identity_verified is False


class FakeAuthorizationTransport:
    def __init__(self) -> None:
        self.calls = []

    def complete_authorization(self, **kwargs):
        self.calls.append(kwargs)
        return IdentityVerificationResult(
            subject_ref="provider-subject-1",
            status="verified",
            provider="digilocker",
            method="requester_oauth",
            verified_claims={"name": "Citizen", "raw": "discard"},
            consent_id="consent-1",
        )


def test_authorization_flow_uses_state_pkce_nonce_and_consumes_state_once():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    transport = FakeAuthorizationTransport()
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    values = iter(["state-value", "verifier-value", "nonce-value"])
    with Session(engine) as session:
        service = IdentityAuthorizationService(
            transport,
            SqlAlchemyAuthorizationStateRepository(
                session, FernetIdentityStateCipher(Fernet.generate_key().decode())
            ),
            IdentityVerificationService(
                SandboxDigiLockerVerifier(),
                SqlAlchemyIdentityVerificationRepository(session),
                allowed_claim_keys=frozenset({"name"}),
            ),
            client_id="requester-client",
            authorization_endpoint="https://digilocker.example/authorize?provider=api-setu",
            redirect_uri="https://app.example/api/v1/identity/digilocker/callback",
            scope="openid requester.verify",
            authorization_parameters={
                "purpose": "verification",
                "state": "must-not-override",
                "redirect_uri": "https://attacker.example/callback",
            },
            token_factory=lambda length: next(values),
            clock=lambda: now,
        )
        url, expires_at = service.start(
            AuthenticatedPrincipal(subject_ref="oidc:citizen-1")
        )
        query = parse_qs(urlsplit(url).query)
        verifier = "verifier-value"
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        assert query["client_id"] == ["requester-client"]
        assert query["code_challenge"] == [expected_challenge]
        assert query["code_challenge_method"] == ["S256"]
        assert query["nonce"] == ["nonce-value"]
        assert query["state"] == ["state-value"]
        assert query["purpose"] == ["verification"]
        assert query["redirect_uri"] == ["https://app.example/api/v1/identity/digilocker/callback"]
        assert expires_at == now + timedelta(minutes=10)

        result = service.complete(state="state-value", code="authorization-code", error=None)

        assert result.subject_ref == "oidc:citizen-1"
        assert result.status == "verified"
        assert result.verification_id
        assert transport.calls[0]["code_verifier"] == verifier
        assert transport.calls[0]["nonce"] == "nonce-value"
        assert transport.calls[0]["expected_state"] == "state-value"
        assert transport.calls[0]["expected_subject_ref"] == "oidc:citizen-1"
        with pytest.raises(IdentityAuthorizationRejected):
            service.complete(state="state-value", code="authorization-code", error=None)

        state_record = session.query(IdentityAuthorizationStateRecord).one()
        assert "verifier-value" not in state_record.code_verifier_ciphertext
        assert state_record.consumed_at is not None


def test_api_identity_endpoints_require_server_identity_and_return_minimal_callback():
    class FakeService:
        def start(self, principal):
            assert principal.subject_ref == "oidc:citizen-1"
            return "https://digilocker.example/authorize?state=server-state", datetime(
                2026, 8, 5, tzinfo=timezone.utc
            )

        def complete(self, *, state, code, error):
            assert (state, code, error) == ("server-state", "code", None)
            return type("Record", (), {"verification_id": "verification-1", "status": "verified"})()

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(subject_ref="oidc:citizen-1"),
        identity_authorization_service_factory=lambda session: FakeService(),  # type: ignore[arg-type]
    )
    client = TestClient(app)

    start = client.post("/api/v1/identity/digilocker/start")
    callback = client.get(
        "/api/v1/identity/digilocker/callback?state=server-state&code=code"
    )

    assert start.status_code == 200
    assert start.json()["authorization_url"].startswith("https://digilocker.example")
    assert callback.status_code == 200
    assert callback.json() == {
        "verification_id": "verification-1",
        "status": "verified",
    }


def test_api_identity_status_is_citizen_scoped_and_exposes_no_claims():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    with Session(engine) as session:
        SqlAlchemyIdentityVerificationRepository(session).save(
            IdentityVerificationResult(
                subject_ref="oidc:citizen-status",
                status="verified",
                provider="digilocker",
                method="requester_oauth",
                verified_claims={"name": "must-not-leak"},
                consent_id="consent-status",
                verified_at=now,
            ),
            reference_hash="b" * 64,
            retention_until=None,
            now=now,
        )

    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            subject_ref="oidc:citizen-status"
        ),
    )
    response = TestClient(app).get("/api/v1/identity/digilocker/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "digilocker"
    assert payload["status"] == "verified"
    assert payload["verification_id"]
    assert payload["verified_at"].startswith("2026-08-05T00:00:00")
    assert payload["expires_at"] is None
    assert "must-not-leak" not in response.text
