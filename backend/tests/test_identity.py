from datetime import datetime, timezone
from time import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.application.identity import IdentityVerificationService
from backend.app.contracts.identity import AuthenticatedPrincipal, AuthenticationError
from backend.app.infrastructure.db import Base, IdentityVerificationRecord
from backend.app.infrastructure.identity import (
    DigiLockerRequesterVerifier,
    RequesterVerificationPayload,
    SandboxDigiLockerVerifier,
)
from backend.app.infrastructure.identity_repositories import (
    SqlAlchemyIdentityVerificationRepository,
)
from backend.app.infrastructure.auth import OidcBearerTokenVerifier


def test_sandbox_digilocker_verification_is_deterministic_and_minimal():
    verifier = SandboxDigiLockerVerifier()

    first = verifier.verify("consent-123")
    second = verifier.verify("consent-123")

    assert first.subject_ref == second.subject_ref
    assert first.consent_id == second.consent_id
    assert first.status == "verified"
    assert first.provider == "digilocker"
    assert first.method == "sandbox"
    assert first.verified_claims == {}
    assert first.subject_ref.startswith("digilocker:sandbox:")


def test_principal_is_server_derived_and_verification_is_explicit():
    principal = AuthenticatedPrincipal(
        subject_ref="digilocker:citizen-1", identity_verified=True
    )

    assert principal.subject_ref == "digilocker:citizen-1"
    assert principal.identity_verified is True


class FakeRequesterTransport:
    def verify_consent(self, consent_reference: str) -> RequesterVerificationPayload:
        assert consent_reference == "consent-requester-1"
        return RequesterVerificationPayload(
            subject_ref="digilocker:citizen-requester",
            status="verified",
            consent_id="requester-consent-1",
            verified_claims={"name": "Citizen", "raw_document": "must-not-persist"},
        )


def test_requester_adapter_allows_only_explicit_minimum_claims():
    verifier = DigiLockerRequesterVerifier(
        FakeRequesterTransport(), allowed_claim_keys=frozenset({"name"})
    )

    result = verifier.verify("consent-requester-1")

    assert result.method == "requester_oauth"
    assert result.verified_claims == {"name": "Citizen"}


def test_identity_verification_persists_minimal_result_and_deduplicates_reference():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    verifier = DigiLockerRequesterVerifier(
        FakeRequesterTransport(), allowed_claim_keys=frozenset({"name"})
    )

    with Session(engine) as session:
        service = IdentityVerificationService(
            verifier,
            SqlAlchemyIdentityVerificationRepository(session),
            allowed_claim_keys=frozenset({"name"}),
        )
        first = service.verify(
            "consent-requester-1", retention_until=None, now=now
        )
        second = service.verify(
            "consent-requester-1",
            retention_until=datetime(2027, 1, 1, tzinfo=timezone.utc),
            now=now,
        )

        assert first.verification_id == second.verification_id
        assert first.subject_ref == "digilocker:citizen-requester"
        assert session.query(IdentityVerificationRecord).count() == 1


class StaticSigningKeyClient:
    def __init__(self, key: object) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> object:
        del token
        return type("SigningKey", (), {"key": self.key})()


def test_oidc_bearer_verifier_requires_signature_issuer_audience_and_verified_claim():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    now = int(time())
    token = jwt.encode(
        {
            "iss": "https://issuer.example",
            "aud": "ai-neta-api",
            "sub": "citizen-oidc-1",
            "iat": now,
            "exp": now + 300,
            "identity_verified": True,
            "roles": ["citizen"],
            "scope": "complaints:write complaints:read",
        },
        private_key,
        algorithm="RS256",
    )
    verifier = OidcBearerTokenVerifier(
        issuer="https://issuer.example",
        audience="ai-neta-api",
        jwks_url="https://issuer.example/.well-known/jwks.json",
        jwks_client=StaticSigningKeyClient(public_key),
    )

    principal = verifier.authenticate(f"Bearer {token}")

    assert principal.subject_ref == "oidc:citizen-oidc-1"
    assert principal.identity_verified is True
    assert principal.scopes == frozenset({"complaints:write", "complaints:read"})

    with pytest.raises(AuthenticationError):
        verifier.authenticate("Bearer not-a-token")
    with pytest.raises(AuthenticationError):
        verifier.authenticate("Basic not-a-token")
