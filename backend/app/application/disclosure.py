"""Citizen disclosure-consent command and policy boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol
from uuid import UUID

from backend.app.contracts.complaints import (
    DisclosureConsentRequest,
    DisclosureConsentResponse,
)
from backend.app.contracts.identity import AuthenticatedPrincipal


class DisclosureConsentConflict(ValueError):
    """The one-time consent command conflicts with stored consent."""


class DisclosurePolicyUnavailable(RuntimeError):
    """Public disclosure is not enabled by an approved deployment policy."""


class DisclosureConsentRepository(Protocol):
    def set_disclosure_consent(
        self,
        citizen_id: str,
        complaint_id: UUID,
        request: DisclosureConsentRequest,
        *,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> DisclosureConsentResponse: ...


class DisclosureConsentService:
    """Record a single explicit disclosure choice without exposing PII."""

    def __init__(
        self,
        repository: DisclosureConsentRepository,
        *,
        public_disclosure_enabled: bool = False,
        policy_version: str = "disclosure-policy.v1",
    ) -> None:
        if not policy_version.strip():
            raise ValueError("Disclosure policy version is required")
        self._repository = repository
        self._public_disclosure_enabled = public_disclosure_enabled
        self._policy_version = policy_version.strip()

    def record(
        self,
        principal: AuthenticatedPrincipal,
        complaint_id: UUID,
        request: DisclosureConsentRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> DisclosureConsentResponse:
        if not principal.subject_ref.strip():
            raise ValueError("Authenticated identity is required")
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        if request.mode == "public_name" and not self._public_disclosure_enabled:
            raise DisclosurePolicyUnavailable(
                "Public disclosure is not enabled by the current policy"
            )
        return self._repository.set_disclosure_consent(
            principal.subject_ref,
            complaint_id,
            request,
            policy_version=self._policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            request_fingerprint=_request_fingerprint(request, self._policy_version),
        )


def _request_fingerprint(request: DisclosureConsentRequest, policy_version: str) -> str:
    canonical = json.dumps(
        {"request": request.model_dump(mode="json"), "policy_version": policy_version},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
