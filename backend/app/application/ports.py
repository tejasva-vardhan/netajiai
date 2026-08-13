"""Provider-neutral ports used by application services."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.app.contracts.ai import ComplaintExtraction, IntentClassification
from backend.app.contracts.complaints import (
    DisclosureConsentRequest,
    DisclosureConsentResponse,
    ComplaintTrackingResponse,
    CreateComplaintRequest,
    ComplaintResponse,
    PublicComplaintTrackingResponse,
)
from backend.app.contracts.workflow_signals import CitizenResolutionOutcome
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.contracts.conversation import ConversationContext
from backend.app.application.routing import RoutingDecision
from backend.app.application.sla import SlaSnapshot
from backend.app.domain.complaints import ComplaintAggregate, ComplaintStatus


class AgentOrchestrator(Protocol):
    """Bounded language operations; never a domain-state authority."""

    def classify_intent(
        self, text: str, *, context: ConversationContext | None = None
    ) -> IntentClassification: ...

    def extract_complaint(
        self,
        text: str,
        *,
        language: str | None = None,
        context: ConversationContext | None = None,
    ) -> ComplaintExtraction: ...


class RoutingResolver(Protocol):
    """Resolve jurisdiction from server-owned evidence, never client hints."""

    def resolve(
        self,
        principal: AuthenticatedPrincipal,
        evidence_asset_ids: tuple[UUID, ...],
    ) -> RoutingDecision: ...


class RoutingActivationResolver(Protocol):
    """Resolve a pending complaint using server-owned routing evidence."""

    def resolve(self, complaint_id: UUID) -> RoutingDecision: ...


class EventPublisher(Protocol):
    """Publishes committed events through an outbox-backed adapter."""

    def publish(self, event: object) -> None: ...


class ComplaintSubmissionRepository(Protocol):
    """Persistence boundary for the verified complaint creation command."""

    def find_by_creation_key(
        self, citizen_id: str, idempotency_key: str
    ) -> ComplaintResponse | None: ...

    def find_creation_request_fingerprint(
        self, citizen_id: str, idempotency_key: str
    ) -> str | None: ...

    def persist_received(
        self,
        aggregate: ComplaintAggregate,
        request: CreateComplaintRequest,
        principal: AuthenticatedPrincipal,
        routing: RoutingDecision,
        request_fingerprint: str,
        sla_snapshot: SlaSnapshot | None = None,
    ) -> ComplaintResponse: ...

    def find_owned(
        self, citizen_id: str, complaint_id: UUID
    ) -> ComplaintTrackingResponse | None: ...

    def find_public(
        self, complaint_id: UUID
    ) -> PublicComplaintTrackingResponse | None: ...

    def transition(
        self,
        complaint_id: UUID,
        *,
        to_status: ComplaintStatus,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
        escalation_level: int | None = None,
        public_disclosure_eligible: bool | None = None,
        closure_proof_claim_id: UUID | None = None,
        citizen_resolution_outcome: CitizenResolutionOutcome | None = None,
        request_fingerprint: str = "",
    ) -> ComplaintTrackingResponse | None: ...

    def activate_routing(
        self,
        complaint_id: UUID,
        *,
        routing: RoutingDecision,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> ComplaintTrackingResponse | None: ...

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
