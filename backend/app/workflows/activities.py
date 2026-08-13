"""Temporal activities that call application services through real adapters."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from uuid import uuid4
from typing import Any

from temporalio import activity
from sqlalchemy.orm import Session

from backend.app.application.complaints import ComplaintTransitionService
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.domain.complaints import ComplaintStatus
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository
from backend.app.infrastructure.closure import SqlAlchemyClosureProofRepository
from backend.app.infrastructure.silence import SqlAlchemySilenceEventRepository
from backend.app.application.silence import silence_request_fingerprint
from backend.app.workflows.complaint_lifecycle import SilenceActivityInput, TransitionActivityInput


SessionFactory = Callable[[], AbstractContextManager[Session]]


def build_transition_activity(session_factory: SessionFactory) -> Any:
    """Build the registered activity with an injected database boundary."""

    @activity.defn(name="apply_complaint_transition")
    async def apply_complaint_transition(input: TransitionActivityInput) -> dict[str, Any]:
        with session_factory() as session:
            service = ComplaintTransitionService(
                SqlAlchemyComplaintSubmissionRepository(session),
                closure_proof_repository=SqlAlchemyClosureProofRepository(session),
                policy_version=input.policy_version,
            )
            result = service.transition(
                AuthenticatedPrincipal(
                    subject_ref="temporal-workflow",
                    roles=frozenset({"workflow"}),
                    scopes=frozenset({"complaint:transition"}),
                    identity_verified=True,
                ),
                input.complaint_id,
                ComplaintStatus(input.to_status),
                idempotency_key=input.idempotency_key,
                correlation_id=input.correlation_id,
                escalation_level=input.escalation_level,
                public_disclosure_eligible=input.public_disclosure_eligible,
                closure_proof_claim_id=input.closure_proof_claim_id,
                citizen_resolution_outcome=input.citizen_resolution_outcome,
            )
            return {"complaint_id": str(result.complaint_id), "status": result.status.value}

    return apply_complaint_transition


def build_silence_activity(session_factory: SessionFactory) -> Any:
    """Build the append-only deadline fact activity with an injected database."""

    @activity.defn(name="record_complaint_silence")
    async def record_complaint_silence(input: SilenceActivityInput) -> dict[str, Any]:
        with session_factory() as session:
            fingerprint = silence_request_fingerprint(
                complaint_id=input.complaint_id,
                workflow_id=input.workflow_id,
                reason_code=input.reason_code,
                status=input.status,
                deadline_at=input.deadline_at,
                escalation_level=input.escalation_level,
                escalation_count=input.escalation_count,
                policy_version=input.policy_version,
            )
            event = SqlAlchemySilenceEventRepository(session).reserve(
                event_id=uuid4(),
                complaint_id=input.complaint_id,
                workflow_id=input.workflow_id,
                reason_code=input.reason_code,
                status=input.status,
                deadline_at=input.deadline_at,
                observed_at=input.observed_at,
                escalation_level=input.escalation_level,
                escalation_count=input.escalation_count,
                policy_version=input.policy_version,
                idempotency_key=input.idempotency_key,
                request_fingerprint=fingerprint,
            )
            return {"event_id": str(event.event_id), "complaint_id": str(event.complaint_id)}

    return record_complaint_silence
