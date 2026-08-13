"""Complaint submission application service.

This service coordinates ports and persistence. Lifecycle authority remains in
the deterministic domain aggregate; evidence acceptance is delegated to an
explicit adapter and cannot silently become a local fallback in production.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.application.closure import (
    ClosureProofRejected,
    ClosureProofRepository,
    ClosureProofRequired,
)
from backend.app.application.ports import ComplaintSubmissionRepository
from backend.app.application.ports import RoutingResolver
from backend.app.application.routing import RoutingDecision, RoutingResolverUnavailable
from backend.app.application.sla import SlaPolicy, SlaPolicyUnavailable, SyntheticSlaPolicy
from backend.app.contracts.complaints import (
    ComplaintTrackingResponse,
    CreateComplaintRequest,
    ComplaintResponse,
    PublicComplaintTrackingResponse,
)
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.contracts.workflow_signals import CitizenResolutionOutcome
from backend.app.application.authorization import has_capability
from backend.app.domain.complaints import ComplaintAggregate, ComplaintStatus


@dataclass(frozen=True, slots=True)
class EvidenceVerificationRequest:
    evidence_asset_ids: tuple[UUID, ...]
    issue_type: str
    citizen_confirmation: bool


@dataclass(frozen=True, slots=True)
class EvidenceVerificationResult:
    accepted: bool
    reason: str = ""


class EvidenceVerifier(Protocol):
    def verify(
        self,
        principal: AuthenticatedPrincipal,
        request: EvidenceVerificationRequest,
    ) -> EvidenceVerificationResult: ...


class SubmissionRejected(ValueError):
    """Raised when identity or required evidence is not acceptable."""


class ComplaintSubmissionConflict(ValueError):
    """Raised when an idempotency key is reused for a different command."""


class EvidenceVerificationUnavailable(RuntimeError):
    """Raised when no production evidence adapter has been configured."""


class UnconfiguredEvidenceVerifier:
    def verify(
        self,
        principal: AuthenticatedPrincipal,
        request: EvidenceVerificationRequest,
    ) -> EvidenceVerificationResult:
        del principal, request
        raise EvidenceVerificationUnavailable(
            "Evidence verification adapter is not configured"
        )


class PublicTrackingTokenCodec(Protocol):
    def encode(self, complaint_id: UUID) -> str: ...

    def decode(self, token: str) -> UUID | None: ...


class ComplaintNotFound(LookupError):
    """Raised when a complaint is not owned by the authenticated citizen."""


class TransitionNotAuthorized(PermissionError):
    """Raised when a principal lacks a lifecycle-transition capability."""


class TransitionIdempotencyConflict(ValueError):
    """Raised when a transition key is reused for a different command."""


class ComplaintSubmissionService:
    def __init__(
        self,
        repository: ComplaintSubmissionRepository,
        evidence_verifier: EvidenceVerifier,
        *,
        policy_version: str = "complaint-policy.v1",
        tracking_token_codec: PublicTrackingTokenCodec | None = None,
        routing_resolver: RoutingResolver | None = None,
        sla_policy: SlaPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._evidence_verifier = evidence_verifier
        self._policy_version = policy_version
        self._tracking_token_codec = tracking_token_codec
        self._routing_resolver = routing_resolver
        self._sla_policy = sla_policy or SyntheticSlaPolicy()

    def create(
        self,
        principal: AuthenticatedPrincipal,
        request: CreateComplaintRequest,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> ComplaintResponse:
        if not principal.subject_ref.strip() or not principal.identity_verified:
            raise SubmissionRejected("Verified citizen identity is required")
        if not idempotency_key.strip():
            raise SubmissionRejected("Idempotency-Key is required")
        if len(request.evidence_asset_ids) != len(set(request.evidence_asset_ids)):
            raise SubmissionRejected("Evidence assets must be unique")

        request_fingerprint = _request_fingerprint(request)

        existing = self._repository.find_by_creation_key(
            principal.subject_ref, idempotency_key
        )
        if existing is not None:
            stored_fingerprint = self._repository.find_creation_request_fingerprint(
                principal.subject_ref, idempotency_key
            )
            if stored_fingerprint != request_fingerprint:
                raise ComplaintSubmissionConflict(
                    "Complaint idempotency key belongs to another request"
                )
            return self._with_tracking_token(existing)

        verification = self._evidence_verifier.verify(
            principal,
            EvidenceVerificationRequest(
                evidence_asset_ids=tuple(request.evidence_asset_ids),
                issue_type=request.issue_type,
                citizen_confirmation=request.citizen_confirmation,
            )
        )
        if not verification.accepted:
            raise SubmissionRejected(verification.reason or "Evidence was not accepted")

        try:
            routing = (
                self._routing_resolver.resolve(
                    principal, tuple(request.evidence_asset_ids)
                )
                if self._routing_resolver is not None
                else RoutingDecision.mapping_in_progress()
            )
        except Exception as exc:
            raise RoutingResolverUnavailable("Routing could not be safely evaluated") from exc

        try:
            sla_snapshot = self._sla_policy.resolve(request.issue_type)
        except Exception as exc:
            raise SlaPolicyUnavailable("SLA policy could not be safely resolved") from exc

        aggregate = ComplaintAggregate.receive(
            uuid4(),
            actor_type="citizen",
            actor_id=principal.subject_ref,
            policy_version=self._policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        response = self._repository.persist_received(
            aggregate,
            request,
            principal,
            routing,
            request_fingerprint,
            sla_snapshot=sla_snapshot,
        )
        return self._with_tracking_token(response)

    def _with_tracking_token(self, response: ComplaintResponse) -> ComplaintResponse:
        if self._tracking_token_codec is None:
            return response
        return response.model_copy(
            update={"tracking_token": self._tracking_token_codec.encode(response.complaint_id)}
        )


def _request_fingerprint(request: CreateComplaintRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _transition_fingerprint(
    actor_id: str,
    to_status: ComplaintStatus,
    policy_version: str,
    escalation_level: int | None,
    public_disclosure_eligible: bool | None,
    closure_proof_claim_id: UUID | None,
    citizen_resolution_outcome: CitizenResolutionOutcome | None,
) -> str:
    canonical = json.dumps(
        {
            "actor_id": actor_id,
            "to_status": to_status.value,
            "policy_version": policy_version,
            "escalation_level": escalation_level,
            "public_disclosure_eligible": public_disclosure_eligible,
            "closure_proof_claim_id": str(closure_proof_claim_id)
            if closure_proof_claim_id is not None
            else None,
            "citizen_resolution_outcome": citizen_resolution_outcome,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ComplaintTrackingService:
    def __init__(self, repository: ComplaintSubmissionRepository) -> None:
        self._repository = repository

    def get(
        self, principal: AuthenticatedPrincipal, complaint_id: UUID
    ) -> ComplaintTrackingResponse:
        response = self._repository.find_owned(principal.subject_ref, complaint_id)
        if response is None:
            raise ComplaintNotFound("Complaint was not found")
        return response


class PublicComplaintTrackingService:
    """Resolve a receipt capability and return only the public projection."""

    def __init__(
        self,
        repository: ComplaintSubmissionRepository,
        token_codec: PublicTrackingTokenCodec,
    ) -> None:
        self._repository = repository
        self._token_codec = token_codec

    def get(self, tracking_token: str) -> PublicComplaintTrackingResponse:
        complaint_id = self._token_codec.decode(tracking_token)
        if complaint_id is None:
            raise ComplaintNotFound("Complaint was not found")
        response = self._repository.find_public(complaint_id)
        if response is None:
            raise ComplaintNotFound("Complaint was not found")
        return response


class ComplaintTransitionService:
    def __init__(
        self,
        repository: ComplaintSubmissionRepository,
        *,
        policy_version: str = "complaint-policy.v1",
        closure_proof_repository: ClosureProofRepository | None = None,
    ) -> None:
        self._repository = repository
        self._policy_version = policy_version
        self._closure_proof_repository = closure_proof_repository

    def transition(
        self,
        principal: AuthenticatedPrincipal,
        complaint_id: UUID,
        to_status: ComplaintStatus,
        *,
        idempotency_key: str,
        correlation_id: str,
        escalation_level: int | None = None,
        public_disclosure_eligible: bool | None = None,
        closure_proof_claim_id: UUID | None = None,
        citizen_resolution_outcome: CitizenResolutionOutcome | None = None,
    ) -> ComplaintTrackingResponse:
        if not has_capability(principal, "complaint.transition"):
            raise TransitionNotAuthorized("Lifecycle transition capability is required")
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        if to_status == ComplaintStatus.FIX_REPORTED:
            if closure_proof_claim_id is None:
                raise ClosureProofRequired("A fix report requires an accepted proof claim")
            if self._closure_proof_repository is None:
                raise ClosureProofRejected("Closure proof repository is not configured")
            claim = self._closure_proof_repository.find_for_complaint(
                complaint_id, closure_proof_claim_id
            )
            if claim is None or claim.status != "accepted":
                raise ClosureProofRejected("The closure proof claim is not accepted")
        actor_type = "workflow" if "workflow" in principal.roles else "operator"
        result = self._repository.transition(
            complaint_id,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=principal.subject_ref,
            policy_version=self._policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            escalation_level=escalation_level,
            public_disclosure_eligible=public_disclosure_eligible,
            closure_proof_claim_id=closure_proof_claim_id,
            citizen_resolution_outcome=citizen_resolution_outcome,
            request_fingerprint=_transition_fingerprint(
                principal.subject_ref,
                to_status,
                self._policy_version,
                escalation_level,
                public_disclosure_eligible,
                closure_proof_claim_id,
                citizen_resolution_outcome,
            ),
        )
        if result is None:
            raise ComplaintNotFound("Complaint was not found")
        return result
