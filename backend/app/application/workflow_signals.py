"""Durable, capability-checked commands for Temporal workflow signals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.app.application.closure import (
    ClosureProofClaim,
    ClosureProofConflict,
    ClosureProofRejected,
    ClosureProofRepository,
    ClosureProofRequired,
    ClosureProofType,
    ClosureProofUnavailable,
    ClosureProofVerifier,
)
from backend.app.application.authorization import has_capability
from backend.app.application.complaints import ComplaintTrackingService
from backend.app.application.department_replies import (
    DepartmentReply,
    DepartmentReplyConflict,
    DepartmentReplyRepository,
    DeterministicWeakReplyClassifier,
    WeakReplyClassifier,
    normalize_reply_text,
    reply_text_hash,
)
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.contracts.workflow_signals import (
    CitizenResolutionOutcome,
    WorkflowSignalResponse,
)
from backend.app.domain.complaints import ComplaintStatus


SignalKind = Literal[
    "routing_activation",
    "department_response",
    "citizen_confirmation",
]


@dataclass(frozen=True, slots=True)
class WorkflowSignalReceipt:
    signal_id: UUID
    complaint_id: UUID
    signal_kind: SignalKind
    request_fingerprint: str
    status: Literal["pending", "sent", "failed"]


@dataclass(frozen=True, slots=True)
class CitizenResolutionResponse:
    response_id: UUID
    complaint_id: UUID
    signal_id: UUID
    outcome: CitizenResolutionOutcome
    request_fingerprint: str
    idempotency_key: str
    created_at: datetime


class CitizenResolutionRepository(Protocol):
    def find(
        self, complaint_id: UUID, idempotency_key: str
    ) -> CitizenResolutionResponse | None: ...

    def latest(self, complaint_id: UUID) -> CitizenResolutionResponse | None: ...

    def reserve(
        self,
        *,
        response_id: UUID,
        complaint_id: UUID,
        signal_id: UUID,
        outcome: CitizenResolutionOutcome,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> CitizenResolutionResponse: ...


class WorkflowSignalRepository(Protocol):
    def find(
        self, complaint_id: UUID, idempotency_key: str
    ) -> WorkflowSignalReceipt | None: ...

    def reserve(
        self,
        *,
        complaint_id: UUID,
        signal_id: UUID,
        signal_kind: SignalKind,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> WorkflowSignalReceipt: ...

    def mark_sent(self, signal_id: UUID, *, now: datetime) -> WorkflowSignalReceipt: ...

    def mark_failed(
        self, signal_id: UUID, *, error_code: str, now: datetime
    ) -> WorkflowSignalReceipt: ...


class WorkflowSignalSender(Protocol):
    async def routing_activation(
        self, complaint_id: UUID, *, signal_id: UUID
    ) -> None: ...

    async def department_response(
        self,
        complaint_id: UUID,
        *,
        signal_id: UUID,
        outcome: Literal["fix_reported", "no_resolution"],
        proof_claim_id: UUID | None,
    ) -> None: ...

    async def citizen_confirmation(
        self,
        complaint_id: UUID,
        *,
        signal_id: UUID,
        outcome: CitizenResolutionOutcome,
    ) -> None: ...


class WorkflowSignalUnavailable(RuntimeError):
    """The durable receipt exists but Temporal could not receive the signal."""


class WorkflowSignalConflict(ValueError):
    """The idempotency key was reused for a different signal payload."""


class WorkflowSignalNotAuthorized(PermissionError):
    """The principal lacks the capability for the requested signal."""


class CitizenConfirmationNotDue(ValueError):
    """The complaint is not currently waiting for a citizen outcome."""


class CitizenResolutionConflict(ValueError):
    """A citizen outcome idempotency key was reused for another outcome."""


class CitizenResolutionUnavailable(RuntimeError):
    """The durable citizen-outcome boundary is not configured."""


class WorkflowSignalService:
    def __init__(
        self,
        repository: WorkflowSignalRepository,
        sender: WorkflowSignalSender,
        proof_verifier: ClosureProofVerifier | None = None,
        proof_repository: ClosureProofRepository | None = None,
        reply_repository: DepartmentReplyRepository | None = None,
        reply_classifier: WeakReplyClassifier | None = None,
        resolution_repository: CitizenResolutionRepository | None = None,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._proof_verifier = proof_verifier
        self._proof_repository = proof_repository
        self._reply_repository = reply_repository
        self._reply_classifier = reply_classifier or DeterministicWeakReplyClassifier()
        self._resolution_repository = resolution_repository

    async def department_response(
        self,
        principal: AuthenticatedPrincipal,
        *,
        complaint_id: UUID,
        outcome: Literal["fix_reported", "no_resolution"],
        reply_text: str | None = None,
        proof_type: ClosureProofType | None = None,
        proof_reference: str | None = None,
        idempotency_key: str,
        now: datetime,
    ) -> WorkflowSignalResponse:
        if not has_capability(principal, "workflow.department_response"):
            raise WorkflowSignalNotAuthorized("An operator capability is required")
        proof_claim: ClosureProofClaim | None = None
        if outcome == "fix_reported":
            proof_claim = self._prepare_closure_proof(
                principal,
                complaint_id=complaint_id,
                proof_type=proof_type,
                proof_reference=proof_reference,
                idempotency_key=idempotency_key,
                now=now,
            )
        elif proof_type is not None or proof_reference is not None:
            raise ClosureProofConflict("Closure proof is only valid for a fix report")
        reply = self._record_department_reply(
            principal,
            complaint_id=complaint_id,
            outcome=outcome,
            reply_text=reply_text,
            proof_claim_id=proof_claim.claim_id if proof_claim is not None else None,
            idempotency_key=idempotency_key,
            now=now,
        )
        payload: dict[str, object] = {"outcome": outcome}
        if proof_claim is not None:
            payload.update(
                {
                    "proof_claim_id": str(proof_claim.claim_id),
                    "proof_type": proof_claim.proof_type,
                    "proof_reference_hash": proof_claim.proof_reference_hash,
                }
            )
        if reply is not None:
            payload.update(
                {
                    "reply_id": str(reply.reply_id),
                    "reply_classification": reply.classification,
                    "reply_text_hash": reply.response_text_hash,
                }
            )
        return await self._send(
            complaint_id=complaint_id,
            kind="department_response",
            payload=payload,
            idempotency_key=idempotency_key,
            now=now,
            send=lambda signal_id: self._sender.department_response(
                complaint_id,
                signal_id=signal_id,
                outcome=outcome,
                proof_claim_id=proof_claim.claim_id if proof_claim is not None else None,
            ),
            reply=reply,
        )

    async def routing_activation(
        self,
        principal: AuthenticatedPrincipal,
        *,
        complaint_id: UUID,
        idempotency_key: str,
        now: datetime,
    ) -> WorkflowSignalResponse:
        if not has_capability(principal, "workflow.routing_activation"):
            raise WorkflowSignalNotAuthorized("A routing-activation capability is required")
        return await self._send(
            complaint_id=complaint_id,
            kind="routing_activation",
            payload={},
            idempotency_key=idempotency_key,
            now=now,
            send=lambda signal_id: self._sender.routing_activation(
                complaint_id, signal_id=signal_id
            ),
        )

    async def citizen_confirmation(
        self,
        principal: AuthenticatedPrincipal,
        *,
        complaint_id: UUID,
        outcome: CitizenResolutionOutcome,
        idempotency_key: str,
        tracking: ComplaintTrackingService,
        now: datetime,
    ) -> WorkflowSignalResponse:
        tracked = tracking.get(principal, complaint_id)
        existing = self._repository.find(complaint_id, idempotency_key)
        if (
            tracked.status
            not in {
                ComplaintStatus.FIX_REPORTED,
                ComplaintStatus.AWAITING_CITIZEN_CONFIRMATION,
            }
            and (existing is None or existing.status != "sent")
        ):
            raise CitizenConfirmationNotDue(
                "Citizen confirmation is not currently requested"
            )
        repository = self._resolution_repository
        if repository is None:
            raise CitizenResolutionUnavailable(
                "Citizen resolution persistence is not configured"
            )
        existing_response = repository.find(complaint_id, idempotency_key)
        if existing_response is None:
            latest = repository.latest(complaint_id)
            if latest is not None and latest.created_at >= tracked.updated_at:
                raise CitizenResolutionConflict(
                    "A citizen outcome has already been recorded for this confirmation request"
                )
        return await self._send(
            complaint_id=complaint_id,
            kind="citizen_confirmation",
            payload={"outcome": outcome},
            idempotency_key=idempotency_key,
            now=now,
            send=lambda signal_id: self._sender.citizen_confirmation(
                complaint_id, signal_id=signal_id, outcome=outcome
            ),
            resolution_outcome=outcome,
        )

    def _prepare_closure_proof(
        self,
        principal: AuthenticatedPrincipal,
        *,
        complaint_id: UUID,
        proof_type: ClosureProofType | None,
        proof_reference: str | None,
        idempotency_key: str,
        now: datetime,
    ) -> ClosureProofClaim:
        if proof_type is None or proof_reference is None or not proof_reference.strip():
            raise ClosureProofRequired("A fix report requires closure proof")
        verifier = self._proof_verifier
        repository = self._proof_repository
        if verifier is None or repository is None:
            raise ClosureProofUnavailable("Closure proof is not configured")
        normalized_reference = proof_reference.strip()
        reference_hash = _proof_reference_hash(normalized_reference)
        proof_fingerprint = _fingerprint(
            complaint_id,
            "closure_proof",
            {
                "proof_type": proof_type,
                "proof_reference_hash": reference_hash,
                "submitted_by": principal.subject_ref,
            },
        )
        existing = repository.find_by_idempotency_key(complaint_id, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != proof_fingerprint:
                raise ClosureProofConflict(
                    "Closure proof idempotency key belongs to another request"
                )
            return existing
        verification = verifier.verify(
            complaint_id=complaint_id,
            proof_type=proof_type,
            proof_reference=normalized_reference,
            submitted_by=principal.subject_ref,
            now=now,
        )
        if not verification.accepted:
            raise ClosureProofRejected(
                verification.reason or "Closure proof was not accepted"
            )
        claim = repository.reserve(
            claim_id=uuid5(
                NAMESPACE_URL,
                f"aineta-closure-proof:{complaint_id}:{idempotency_key}",
            ),
            complaint_id=complaint_id,
            proof_type=proof_type,
            proof_reference_hash=reference_hash,
            submitted_by=principal.subject_ref,
            verifier=verification.verifier,
            idempotency_key=idempotency_key,
            request_fingerprint=proof_fingerprint,
            now=now,
        )
        if claim.request_fingerprint != proof_fingerprint:
            raise ClosureProofConflict(
                "Closure proof idempotency key belongs to another request"
            )
        return claim

    def _record_department_reply(
        self,
        principal: AuthenticatedPrincipal,
        *,
        complaint_id: UUID,
        outcome: Literal["fix_reported", "no_resolution"],
        reply_text: str | None,
        proof_claim_id: UUID | None,
        idempotency_key: str,
        now: datetime,
    ) -> DepartmentReply | None:
        repository = self._reply_repository
        if repository is None:
            return None
        normalized_text = normalize_reply_text(reply_text)
        text_hash = reply_text_hash(normalized_text)
        fingerprint = _fingerprint(
            complaint_id,
            "department_reply",
            {
                "outcome": outcome,
                "response_text_hash": text_hash,
                "proof_claim_id": str(proof_claim_id) if proof_claim_id else None,
                "submitted_by": principal.subject_ref,
            },
        )
        existing = repository.find_by_idempotency_key(complaint_id, idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise DepartmentReplyConflict(
                    "Department reply idempotency key belongs to another request"
                )
            return existing
        duplicate = text_hash is not None and repository.has_text_hash(
            complaint_id, text_hash
        )
        classification, reason = self._reply_classifier.classify(
            normalized_text, duplicate=duplicate
        )
        return repository.reserve(
            reply_id=uuid5(
                NAMESPACE_URL,
                f"aineta-department-reply:{complaint_id}:{idempotency_key}",
            ),
            complaint_id=complaint_id,
            submitted_by=principal.subject_ref,
            outcome=outcome,
            response_text=normalized_text,
            response_text_hash=text_hash,
            classification=classification,
            classification_reason=reason,
            classification_policy_version=self._reply_classifier.policy_version,
            proof_claim_id=proof_claim_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            received_at=now,
        )

    async def _send(
        self,
        *,
        complaint_id: UUID,
        kind: SignalKind,
        payload: dict[str, object],
        idempotency_key: str,
        now: datetime,
        send: Callable[[UUID], Awaitable[None]],
        reply: DepartmentReply | None = None,
        resolution_outcome: CitizenResolutionOutcome | None = None,
    ) -> WorkflowSignalResponse:
        if not idempotency_key.strip():
            raise WorkflowSignalConflict("Idempotency-Key is required")
        fingerprint = _fingerprint(complaint_id, kind, payload)
        existing = self._repository.find(complaint_id, idempotency_key)
        if existing is not None and existing.request_fingerprint != fingerprint:
            raise WorkflowSignalConflict("Signal idempotency key belongs to another request")
        if existing is not None and existing.status == "sent":
            return WorkflowSignalResponse(
                complaint_id=complaint_id,
                signal_id=existing.signal_id,
                accepted=True,
                reply_id=reply.reply_id if reply is not None else None,
                reply_classification=reply.classification if reply is not None else None,
            )
        signal_id = existing.signal_id if existing is not None else uuid5(
            NAMESPACE_URL,
            f"aineta-workflow-signal:{complaint_id}:{kind}:{idempotency_key}",
        )
        receipt = self._repository.reserve(
            complaint_id=complaint_id,
            signal_id=signal_id,
            signal_kind=kind,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            now=now,
        )
        if receipt.request_fingerprint != fingerprint:
            raise WorkflowSignalConflict("Signal idempotency key belongs to another request")
        if resolution_outcome is not None:
            repository = self._resolution_repository
            if repository is None:
                raise CitizenResolutionUnavailable(
                    "Citizen resolution persistence is not configured"
                )
            response = repository.reserve(
                response_id=uuid5(
                    NAMESPACE_URL,
                    f"aineta-citizen-resolution:{complaint_id}:{idempotency_key}",
                ),
                complaint_id=complaint_id,
                signal_id=signal_id,
                outcome=resolution_outcome,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                now=now,
            )
            if (
                response.request_fingerprint != fingerprint
                or response.outcome != resolution_outcome
            ):
                raise CitizenResolutionConflict(
                    "Citizen resolution idempotency key belongs to another outcome"
                )
        try:
            await send(signal_id)
        except Exception as exc:
            self._repository.mark_failed(
                signal_id, error_code=type(exc).__name__[:120], now=now
            )
            raise WorkflowSignalUnavailable(
                "Complaint workflow is temporarily unavailable"
            ) from exc
        self._repository.mark_sent(signal_id, now=now)
        return WorkflowSignalResponse(
            complaint_id=complaint_id,
            signal_id=signal_id,
            accepted=True,
            reply_id=reply.reply_id if reply is not None else None,
            reply_classification=reply.classification if reply is not None else None,
        )


def _fingerprint(complaint_id: UUID, kind: str, payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {"complaint_id": str(complaint_id), "kind": kind, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _proof_reference_hash(proof_reference: str) -> str:
    return hashlib.sha256(proof_reference.encode("utf-8")).hexdigest()
