"""Capability-protected routing activation command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from backend.app.application.ports import RoutingActivationResolver
from backend.app.application.authorization import has_capability
from backend.app.application.routing import RoutingDecision
from backend.app.contracts.complaints import ComplaintTrackingResponse
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.domain.complaints import InvalidTransition, RoutingAlreadyActive


class RoutingActivationNotAuthorized(PermissionError):
    """The principal lacks the routing-activation capability."""


class RoutingActivationUnavailable(RuntimeError):
    """A trusted routing decision is not currently available."""


class RoutingActivationConflict(ValueError):
    """The complaint cannot accept another routing activation."""


@dataclass(frozen=True, slots=True)
class RoutingActivationResult:
    complaint: ComplaintTrackingResponse
    decision: RoutingDecision


class RoutingActivationRepository(Protocol):
    """Submission repository plus the idempotent routing lookup."""

    def find_routing_activation(
        self, complaint_id: UUID, idempotency_key: str
    ) -> RoutingActivationResult | None: ...

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

class RoutingActivationService:
    def __init__(
        self,
        repository: RoutingActivationRepository,
        resolver: RoutingActivationResolver,
        *,
        policy_version: str = "routing-policy.v1",
    ) -> None:
        self._repository = repository
        self._resolver = resolver
        self._policy_version = policy_version

    def activate(
        self,
        principal: AuthenticatedPrincipal,
        complaint_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> RoutingActivationResult:
        if not has_capability(principal, "workflow.routing_activation"):
            raise RoutingActivationNotAuthorized(
                "A routing-activation capability is required"
            )
        if not idempotency_key.strip():
            raise RoutingActivationConflict("Idempotency-Key is required")

        existing = self._repository.find_routing_activation(
            complaint_id, idempotency_key
        )
        if existing is not None:
            return existing

        try:
            decision = self._resolver.resolve(complaint_id)
        except Exception as exc:
            raise RoutingActivationUnavailable(
                "Routing could not be safely evaluated"
            ) from exc
        if decision.state != "active" or not decision.jurisdiction_code:
            raise RoutingActivationUnavailable(
                "Verified routing is not available for this complaint"
            )
        if not decision.snapshot_ref:
            raise RoutingActivationUnavailable(
                "Routing snapshot is required before activation"
            )

        try:
            complaint = self._repository.activate_routing(
                complaint_id,
                routing=decision,
                actor_type="workflow" if "workflow" in principal.roles else "operator",
                actor_id=principal.subject_ref,
                policy_version=self._policy_version,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        except (InvalidTransition, RoutingAlreadyActive) as exc:
            raise RoutingActivationConflict(str(exc)) from exc
        if complaint is None:
            raise RoutingActivationConflict("Complaint was not found")
        return RoutingActivationResult(complaint=complaint, decision=decision)
