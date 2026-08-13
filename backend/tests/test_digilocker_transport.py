from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from backend.app.infrastructure.digilocker import (
    DigiLockerTransportError,
    HttpDigiLockerAuthorizationTransport,
    TemporaryLocalIdentityTransport,
)


def test_requester_transport_exchanges_code_and_allowlists_user_claims():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            assert request.headers["authorization"].startswith("Basic ")
            fields = parse_qs(request.content.decode("utf-8"))
            assert fields["grant_type"] == ["authorization_code"]
            assert fields["code_verifier"] == ["verifier"]
            assert fields["redirect_uri"] == ["https://app.example/callback"]
            return httpx.Response(
                200,
                json={
                    "access_token": "secret-token-that-must-not-persist",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "consent_valid_till": 1_900_000_000,
                    "refresh_token": "secret-refresh-token",
                },
            )
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer secret-token-that-must-not-persist"
            return httpx.Response(
                200,
                json={
                    "digilockerid": "provider-id",
                    "name": "Citizen Name",
                    "dob": "31121970",
                    "picture": "raw-image-data",
                },
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = HttpDigiLockerAuthorizationTransport(
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://provider.example/token",
        user_endpoint="https://provider.example/user",
        allowed_claim_keys=frozenset({"digilockerid", "name"}),
        client=client,
    )

    result = transport.complete_authorization(
        code="one-time-code",
        code_verifier="verifier",
        nonce="nonce",
        redirect_uri="https://app.example/callback",
        expected_state="state",
        expected_subject_ref="oidc:citizen-1",
    )

    assert result.subject_ref == "oidc:citizen-1"
    assert result.status == "verified"
    assert result.verified_claims == {
        "digilockerid": "provider-id",
        "name": "Citizen Name",
    }
    assert "secret-token" not in result.model_dump_json()
    assert "raw-image-data" not in result.model_dump_json()
    assert result.expires_at is not None


def test_requester_transport_fails_without_a_valid_token_or_user_response():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"token_type": "Bearer"})

    transport = HttpDigiLockerAuthorizationTransport(
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://provider.example/token",
        user_endpoint="https://provider.example/user",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(DigiLockerTransportError, match="token response is invalid"):
        transport.complete_authorization(
            code="code",
            code_verifier="verifier",
            nonce="nonce",
            redirect_uri="https://app.example/callback",
            expected_state="state",
            expected_subject_ref="oidc:citizen-1",
        )


def test_requester_transport_requires_https_provider_endpoints():
    with pytest.raises(ValueError, match="token_endpoint must be an HTTPS URL"):
        HttpDigiLockerAuthorizationTransport(
            client_id="client-id",
            client_secret="client-secret",
            token_endpoint="http://provider.example/token",
            user_endpoint="https://provider.example/user",
        )


def test_temporary_identity_transport_binds_code_to_state_and_expires():
    transport = TemporaryLocalIdentityTransport("local-secret-32-bytes-012345678901")
    code = transport.issue_code("state-value")

    result = transport.complete_authorization(
        code=code,
        code_verifier="unused",
        nonce="unused",
        redirect_uri="http://localhost/callback",
        expected_state="state-value",
        expected_subject_ref="oidc:citizen-1",
    )

    assert result.provider == "temporary"
    assert result.method == "temporary_local"
    assert result.subject_ref == "oidc:citizen-1"
    with pytest.raises(DigiLockerTransportError, match="does not match state"):
        transport.complete_authorization(
            code=code,
            code_verifier="unused",
            nonce="unused",
            redirect_uri="http://localhost/callback",
            expected_state="another-state",
            expected_subject_ref="oidc:citizen-1",
        )
