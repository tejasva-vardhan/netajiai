"""Identity and verification contracts exposed across application boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VerificationStatus = Literal["verified", "pending", "rejected", "unavailable"]
IdentityProvider = Literal["digilocker", "temporary"]


class IdentityVerificationResult(BaseModel):
    """Minimal result of a consented identity verification attempt.

    Raw DigiLocker documents are deliberately not part of this contract. The
    application should retain only the claims it actually needs.
    """

    model_config = ConfigDict(extra="forbid")

    subject_ref: str = Field(min_length=1, max_length=255)
    status: VerificationStatus
    provider: IdentityProvider
    method: Literal["requester_oauth", "sandbox", "temporary_local"]
    verified_claims: dict[str, str] = Field(default_factory=dict)
    consent_id: str = Field(min_length=1, max_length=255)
    verified_at: datetime | None = None
    expires_at: datetime | None = None


class IdentityAuthorizationStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_url: str = Field(min_length=1, max_length=4_000)
    expires_at: datetime


class IdentityAuthorizationCallbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(min_length=1, max_length=255)
    status: VerificationStatus


class IdentityVerificationStatusResponse(BaseModel):
    """Safe status projection for the signed-in citizen's verification."""

    model_config = ConfigDict(extra="forbid")

    provider: IdentityProvider
    status: VerificationStatus
    verification_id: str | None = None
    verified_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Server-derived identity used by application commands."""

    subject_ref: str
    roles: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()
    identity_verified: bool = False


class AuthenticationError(ValueError):
    """Raised when a bearer credential cannot establish a principal."""
