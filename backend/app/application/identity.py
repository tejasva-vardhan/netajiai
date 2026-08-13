"""Ports for authentication and DigiLocker verification."""

from __future__ import annotations

import hashlib
import base64
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from backend.app.contracts.identity import (
    AuthenticatedPrincipal,
    IdentityProvider,
    IdentityVerificationResult,
    IdentityVerificationStatusResponse,
)


class IdentityTokenVerifier(Protocol):
    def authenticate(self, authorization_header: str) -> AuthenticatedPrincipal: ...


class DigiLockerVerifier(Protocol):
    def verify(self, consent_reference: str) -> IdentityVerificationResult: ...


class DigiLockerAuthorizationTransport(Protocol):
    """Approved-provider transport for the authorization-code completion.

    The provider-specific token/document calls and claim mapping stay behind
    this port because Requester onboarding supplies the authoritative API
    contract. The application never guesses endpoints or claims.
    """

    def complete_authorization(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
        expected_state: str,
        expected_subject_ref: str,
    ) -> IdentityVerificationResult: ...


@dataclass(frozen=True, slots=True)
class IdentityVerificationRecord:
    verification_id: UUID
    subject_ref: str
    status: str
    provider: str
    method: str
    consent_id: str
    verified_at: datetime | None
    expires_at: datetime | None
    retention_until: datetime | None


class IdentityVerificationRepository(Protocol):
    def find_by_reference_hash(
        self, reference_hash: str
    ) -> IdentityVerificationRecord | None: ...

    def find_latest_for_subject(
        self, subject_ref: str
    ) -> IdentityVerificationRecord | None: ...

    def save(
        self,
        result: IdentityVerificationResult,
        *,
        reference_hash: str,
        retention_until: datetime | None,
        now: datetime,
    ) -> IdentityVerificationRecord: ...


@dataclass(frozen=True, slots=True)
class AuthorizationStateRecord:
    state_hash: str
    subject_ref: str
    code_verifier: str
    nonce: str
    redirect_uri: str
    expires_at: datetime


class AuthorizationStateRepository(Protocol):
    def save(
        self,
        *,
        state_hash: str,
        subject_ref: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
        expires_at: datetime,
        now: datetime,
    ) -> None: ...

    def consume(self, state_hash: str, *, now: datetime) -> AuthorizationStateRecord | None: ...


class IdentityVerificationService:
    """Persist only the minimum result of a consented provider verification."""

    def __init__(
        self,
        verifier: DigiLockerVerifier,
        repository: IdentityVerificationRepository,
        *,
        allowed_claim_keys: frozenset[str] = frozenset(),
    ) -> None:
        self._verifier = verifier
        self._repository = repository
        self._allowed_claim_keys = allowed_claim_keys

    def verify(
        self,
        consent_reference: str,
        *,
        retention_until: datetime | None,
        now: datetime,
    ) -> IdentityVerificationRecord:
        reference = consent_reference.strip()
        if not reference:
            raise ValueError("consent_reference is required")
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        existing = self._repository.find_by_reference_hash(reference_hash)
        if existing is not None:
            return existing
        result = self._verifier.verify(reference)
        return self.persist_result(
            result,
            reference=reference,
            retention_until=retention_until,
            now=now,
        )

    def persist_result(
        self,
        result: IdentityVerificationResult,
        *,
        reference: str,
        retention_until: datetime | None,
        now: datetime,
    ) -> IdentityVerificationRecord:
        reference = reference.strip()
        if not reference:
            raise ValueError("reference is required")
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        existing = self._repository.find_by_reference_hash(reference_hash)
        if existing is not None:
            if existing.subject_ref != result.subject_ref:
                raise ValueError("Identity verification reference belongs to another subject")
            return existing
        result = result.model_copy(
            update={
                "verified_claims": {
                    key: value
                    for key, value in result.verified_claims.items()
                    if key in self._allowed_claim_keys
                }
            }
        )
        return self._repository.save(
            result,
            reference_hash=reference_hash,
            retention_until=retention_until,
            now=now,
        )


class IdentityVerificationStatusService:
    """Expose only the current citizen-scoped verification status."""

    def __init__(
        self,
        repository: IdentityVerificationRepository,
        *,
        provider: IdentityProvider = "digilocker",
    ) -> None:
        self._repository = repository
        self._provider = provider

    def get(self, principal: AuthenticatedPrincipal) -> IdentityVerificationStatusResponse:
        if not principal.subject_ref.strip():
            raise ValueError("Authenticated identity is required")
        record = self._repository.find_latest_for_subject(principal.subject_ref)
        if record is None:
            if principal.identity_verified:
                return IdentityVerificationStatusResponse(
                    provider=self._provider,
                    status="verified",
                    verified_at=datetime.now(timezone.utc),
                )
            return IdentityVerificationStatusResponse(
                provider=self._provider, status="unavailable"
            )
        status = record.status
        expires_at = record.expires_at
        comparable_expiry = (
            expires_at.replace(tzinfo=timezone.utc)
            if expires_at is not None and expires_at.tzinfo is None
            else expires_at
        )
        if (
            status == "verified"
            and comparable_expiry is not None
            and comparable_expiry <= datetime.now(timezone.utc)
        ):
            status = "unavailable"
        return IdentityVerificationStatusResponse(
            provider=record.provider,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            verification_id=str(record.verification_id),
            verified_at=record.verified_at,
            expires_at=record.expires_at,
        )


class IdentityAuthorizationRejected(ValueError):
    """Raised when the citizen or provider rejects the authorization attempt."""


class IdentityAuthorizationService:
    """Coordinate OAuth state/PKCE and persist the resulting verification."""

    def __init__(
        self,
        transport: DigiLockerAuthorizationTransport,
        state_repository: AuthorizationStateRepository,
        verification_service: IdentityVerificationService,
        *,
        client_id: str,
        authorization_endpoint: str,
        redirect_uri: str,
        scope: str,
        authorization_parameters: Mapping[str, str] | None = None,
        state_ttl: timedelta = timedelta(minutes=10),
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        required = {
            "client_id": client_id,
            "authorization_endpoint": authorization_endpoint,
            "redirect_uri": redirect_uri,
            "scope": scope,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError("Missing DigiLocker authorization configuration: " + ", ".join(missing))
        if state_ttl <= timedelta(0):
            raise ValueError("state_ttl must be positive")
        self._transport = transport
        self._state_repository = state_repository
        self._verification_service = verification_service
        self._client_id = client_id
        self._authorization_endpoint = authorization_endpoint
        self._redirect_uri = redirect_uri
        self._scope = scope
        self._authorization_parameters = {
            key: value.strip()
            for key, value in (authorization_parameters or {}).items()
            if key.strip() and value.strip()
        }
        self._state_ttl = state_ttl
        self._token_factory = token_factory
        self._clock = clock

    def start(self, principal: AuthenticatedPrincipal) -> tuple[str, datetime]:
        if not principal.subject_ref.strip():
            raise IdentityAuthorizationRejected("Authenticated identity is required")
        now = self._clock()
        expires_at = now + self._state_ttl
        state = self._token_factory(32)
        verifier = self._token_factory(64)
        nonce = self._token_factory(32)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state_hash = hashlib.sha256(state.encode("ascii")).hexdigest()
        authorization_url = self._authorization_url(
            state=state,
            code_challenge=challenge,
            nonce=nonce,
        )
        self._state_repository.save(
            state_hash=state_hash,
            subject_ref=principal.subject_ref,
            code_verifier=verifier,
            nonce=nonce,
            redirect_uri=self._redirect_uri,
            expires_at=expires_at,
            now=now,
        )
        return authorization_url, expires_at

    def complete(
        self,
        *,
        state: str,
        code: str | None,
        error: str | None,
    ) -> IdentityVerificationRecord:
        state = state.strip()
        if not state:
            raise IdentityAuthorizationRejected("OAuth state is required")
        now = self._clock()
        record = self._state_repository.consume(
            hashlib.sha256(state.encode("utf-8")).hexdigest(), now=now
        )
        if record is None:
            raise IdentityAuthorizationRejected("Authorization state is invalid or expired")
        if error:
            raise IdentityAuthorizationRejected("DigiLocker authorization was rejected")
        if not code or not code.strip():
            raise IdentityAuthorizationRejected("Authorization code is required")
        result = self._transport.complete_authorization(
            code=code,
            code_verifier=record.code_verifier,
            nonce=record.nonce,
            redirect_uri=record.redirect_uri,
            expected_state=state,
            expected_subject_ref=record.subject_ref,
        )
        # The authenticated application subject is the owner of this consent
        # attempt; provider subject identifiers are not exposed as account IDs.
        result = result.model_copy(update={"subject_ref": record.subject_ref})
        return self._verification_service.persist_result(
            result,
            reference=result.consent_id,
            retention_until=None,
            now=now,
        )

    def _authorization_url(self, *, state: str, code_challenge: str, nonce: str) -> str:
        parts = urlsplit(self._authorization_endpoint)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(self._authorization_parameters)
        query.update(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "scope": self._scope,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "nonce": nonce,
            }
        )
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )
