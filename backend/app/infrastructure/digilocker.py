"""HTTP transport for the approved DigiLocker Requester authorization flow.

The partner portal supplies the concrete endpoint URLs and credentials. This
adapter performs only the authorization-code exchange and a minimal
authenticated user-details lookup; it never downloads or stores documents.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.app.application.identity import DigiLockerAuthorizationTransport
from backend.app.config import Settings
from backend.app.contracts.identity import IdentityVerificationResult


class DigiLockerTransportError(RuntimeError):
    """The configured Requester transport could not complete safely."""


class TemporaryLocalIdentityTransport(DigiLockerAuthorizationTransport):
    """Short-lived local identity handoff used before DigiLocker approval.

    This is an interim account-verification path, not government identity
    verification. It is only composed for development and test environments.
    """

    def __init__(self, secret: str, *, ttl_seconds: int = 600) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("Local identity transport secret must be at least 32 bytes")
        if ttl_seconds < 1:
            raise ValueError("Local identity transport TTL must be positive")
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def issue_code(self, state: str) -> str:
        expires_at = int(datetime.now(timezone.utc).timestamp()) + self._ttl_seconds
        nonce = secrets.token_urlsafe(18)
        payload = f"{state}.{expires_at}.{nonce}".encode("utf-8")
        signature = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
        return f"local.{payload.decode('utf-8')}.{signature}"

    def complete_authorization(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
        expected_state: str,
        expected_subject_ref: str,
    ) -> IdentityVerificationResult:
        del code_verifier, nonce, redirect_uri
        parts = code.split(".")
        if len(parts) != 5 or parts[0] != "local":
            raise DigiLockerTransportError("Local identity code is invalid")
        # State and nonce are URL-safe and therefore cannot contain a dot.
        if parts[1] != expected_state:
            raise DigiLockerTransportError("Local identity code does not match state")
        payload = ".".join(parts[1:4])
        supplied_signature = parts[4]
        expected_signature = hmac.new(
            self._secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise DigiLockerTransportError("Local identity code is invalid")
        try:
            expires_at = int(parts[2])
        except ValueError as exc:
            raise DigiLockerTransportError("Local identity code is invalid") from exc
        if expires_at <= int(datetime.now(timezone.utc).timestamp()):
            raise DigiLockerTransportError("Local identity code is expired")
        if not expected_subject_ref.strip():
            raise DigiLockerTransportError("Authenticated identity is required")
        now = datetime.now(timezone.utc)
        return IdentityVerificationResult(
            subject_ref=expected_subject_ref,
            status="verified",
            provider="temporary",
            method="temporary_local",
            consent_id="temporary:" + hashlib.sha256(code.encode("utf-8")).hexdigest(),
            verified_at=now,
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        )


class HttpDigiLockerAuthorizationTransport(DigiLockerAuthorizationTransport):
    """Exchange a code and verify the authenticated DigiLocker user response."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        token_endpoint: str,
        user_endpoint: str,
        allowed_claim_keys: frozenset[str] = frozenset(),
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("DigiLocker client credentials are required")
        for name, endpoint in {
            "token_endpoint": token_endpoint,
            "user_endpoint": user_endpoint,
        }.items():
            parsed = httpx.URL(endpoint)
            if parsed.scheme != "https" or not parsed.host:
                raise ValueError(f"{name} must be an HTTPS URL")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_endpoint = token_endpoint
        self._user_endpoint = user_endpoint
        self._allowed_claim_keys = allowed_claim_keys
        self._timeout_seconds = timeout_seconds
        self._client = client

    def complete_authorization(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
        expected_state: str,
        expected_subject_ref: str,
    ) -> IdentityVerificationResult:
        if not code.strip() or not code_verifier.strip() or not expected_subject_ref.strip():
            raise DigiLockerTransportError("DigiLocker authorization input is incomplete")
        # DigiLocker’s Requester API specification documents an OAuth2
        # authorization-code exchange and user-details call, not an ID token
        # carrying an OIDC nonce claim. The application still generates,
        # persists, and sends nonce in the authorization request so this port
        # remains safe for a provider contract that adds OIDC validation; this
        # transport does not claim validation that the current contract does
        # not provide.
        del nonce, expected_state
        if self._client is None:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                return self._complete_with_client(
                    client,
                    code=code,
                    code_verifier=code_verifier,
                    redirect_uri=redirect_uri,
                    expected_subject_ref=expected_subject_ref,
                )
        return self._complete_with_client(
            self._client,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            expected_subject_ref=expected_subject_ref,
        )

    def _complete_with_client(
        self,
        client: httpx.Client,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        expected_subject_ref: str,
    ) -> IdentityVerificationResult:
        try:
            token_response = client.post(
                self._token_endpoint,
                auth=(self._client_id, self._client_secret),
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                },
            )
        except httpx.HTTPError as exc:
            raise DigiLockerTransportError("DigiLocker token exchange is unavailable") from exc
        if token_response.status_code != 200:
            raise DigiLockerTransportError("DigiLocker token exchange was rejected")
        token_payload = _json_object(token_response, "DigiLocker token response")
        access_token = token_payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise DigiLockerTransportError("DigiLocker token response is invalid")
        token_type = token_payload.get("token_type", "Bearer")
        if not isinstance(token_type, str) or token_type.casefold() != "bearer":
            raise DigiLockerTransportError("DigiLocker returned an unsupported token type")

        try:
            user_response = client.get(
                self._user_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            raise DigiLockerTransportError("DigiLocker user verification is unavailable") from exc
        if user_response.status_code != 200:
            raise DigiLockerTransportError("DigiLocker user verification was rejected")
        user_payload = _json_object(user_response, "DigiLocker user response")
        claims = _allowlisted_claims(user_payload, self._allowed_claim_keys)
        now = datetime.now(timezone.utc)
        return IdentityVerificationResult(
            subject_ref=expected_subject_ref,
            status="verified",
            provider="digilocker",
            method="requester_oauth",
            verified_claims=claims,
            consent_id="auth-code:" + hashlib.sha256(code.encode("utf-8")).hexdigest(),
            verified_at=now,
            expires_at=_expiry_from_token(token_payload, now),
        )


def build_digilocker_requester_transport(
    settings: Settings,
    *,
    allowed_claim_keys: frozenset[str] = frozenset(),
    client: httpx.Client | None = None,
) -> HttpDigiLockerAuthorizationTransport:
    """Build the transport from deployment-owned settings for composition modules."""

    return HttpDigiLockerAuthorizationTransport(
        client_id=settings.digilocker_client_id,
        client_secret=settings.digilocker_client_secret,
        token_endpoint=settings.digilocker_token_endpoint,
        user_endpoint=settings.digilocker_user_endpoint,
        allowed_claim_keys=allowed_claim_keys,
        client=client,
    )


def _json_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise DigiLockerTransportError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise DigiLockerTransportError(f"{label} is invalid")
    return payload


def _allowlisted_claims(payload: Mapping[str, Any], allowed: frozenset[str]) -> dict[str, str]:
    claims: dict[str, str] = {}
    for key in allowed:
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            claims[key] = str(value)
    return claims


def _expiry_from_token(payload: Mapping[str, Any], now: datetime) -> datetime | None:
    consent_valid_till = payload.get("consent_valid_till")
    if isinstance(consent_valid_till, (int, float)) and consent_valid_till > 0:
        return datetime.fromtimestamp(consent_valid_till, tz=timezone.utc)
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return now + timedelta(seconds=expires_in)
    return None
