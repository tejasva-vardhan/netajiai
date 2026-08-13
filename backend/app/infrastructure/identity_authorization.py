"""Durable encrypted OAuth-state persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Callable
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from backend.app.application.identity import (
    AuthorizationStateRecord,
    AuthorizationStateRepository,
    DigiLockerAuthorizationTransport,
    DigiLockerVerifier,
    IdentityAuthorizationService,
    IdentityVerificationService,
)
from backend.app.config import Settings
from backend.app.infrastructure.db import IdentityAuthorizationStateRecord
from backend.app.infrastructure.identity_repositories import SqlAlchemyIdentityVerificationRepository


class IdentityStateCipher(Protocol):
    def encrypt(self, value: str) -> str: ...

    def decrypt(self, value: str) -> str: ...


class FernetIdentityStateCipher:
    """Encrypt short-lived PKCE material before it reaches the database."""

    def __init__(self, key: str) -> None:
        if not key.strip():
            raise ValueError("Identity state encryption key is required")
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("Identity state encryption key is invalid") from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise ValueError("Identity authorization state cannot be decrypted") from exc


class SqlAlchemyAuthorizationStateRepository(AuthorizationStateRepository):
    def __init__(self, session: Session, cipher: IdentityStateCipher) -> None:
        self._session = session
        self._cipher = cipher

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
    ) -> None:
        self._session.execute(
            delete(IdentityAuthorizationStateRecord).where(
                or_(
                    IdentityAuthorizationStateRecord.expires_at <= now,
                    IdentityAuthorizationStateRecord.consumed_at.is_not(None),
                )
            )
        )
        self._session.add(
            IdentityAuthorizationStateRecord(
                state_hash=state_hash,
                subject_ref=subject_ref,
                code_verifier_ciphertext=self._cipher.encrypt(code_verifier),
                nonce_ciphertext=self._cipher.encrypt(nonce),
                redirect_uri=redirect_uri,
                expires_at=expires_at,
                created_at=now,
            )
        )
        self._session.commit()

    def consume(self, state_hash: str, *, now: datetime) -> AuthorizationStateRecord | None:
        record = self._session.scalar(
            select(IdentityAuthorizationStateRecord)
            .where(IdentityAuthorizationStateRecord.state_hash == state_hash)
            .with_for_update()
        )
        if record is None:
            return None
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        comparison_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        if record.consumed_at is not None or expires_at <= comparison_now:
            if record.consumed_at is None:
                record.consumed_at = now
                self._session.commit()
            return None
        record.consumed_at = now
        self._session.commit()
        return AuthorizationStateRecord(
            state_hash=record.state_hash,
            subject_ref=record.subject_ref,
            code_verifier=self._cipher.decrypt(record.code_verifier_ciphertext),
            nonce=self._cipher.decrypt(record.nonce_ciphertext),
            redirect_uri=record.redirect_uri,
            expires_at=expires_at,
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_identity_authorization_service_factory(
    settings: Settings,
    *,
    transport: DigiLockerAuthorizationTransport,
    verifier: DigiLockerVerifier,
    allowed_claim_keys: frozenset[str],
) -> Callable[[Session], IdentityAuthorizationService]:
    """Compose request-scoped identity services from approved adapters."""

    cipher = FernetIdentityStateCipher(settings.identity_state_encryption_key)

    def factory(session: Session) -> IdentityAuthorizationService:
        return IdentityAuthorizationService(
            transport,
            SqlAlchemyAuthorizationStateRepository(session, cipher),
            IdentityVerificationService(
                verifier,
                SqlAlchemyIdentityVerificationRepository(session),
                allowed_claim_keys=allowed_claim_keys,
            ),
            client_id=settings.digilocker_client_id,
            authorization_endpoint=settings.digilocker_authorization_endpoint,
            redirect_uri=settings.digilocker_redirect_uri,
            scope=settings.digilocker_scope,
            authorization_parameters={"purpose": settings.digilocker_purpose},
        )

    return factory
