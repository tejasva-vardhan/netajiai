"""Deterministic complaint aggregate and transition rules.

The model may provide extraction signals, but only this domain boundary can
change complaint lifecycle state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class ComplaintStatus(StrEnum):
    RECEIVED = "received"
    VERIFYING = "verifying"
    ROUTING_REVIEW = "routing_review"
    MAPPING_IN_PROGRESS = "mapping_in_progress"
    SENT = "sent"
    AWAITING_RESPONSE = "awaiting_response"
    ESCALATED = "escalated"
    FIX_REPORTED = "fix_reported"
    AWAITING_CITIZEN_CONFIRMATION = "awaiting_citizen_confirmation"
    CLOSED = "closed"
    REOPENED = "reopened"
    NEEDS_CLARIFICATION = "needs_clarification"
    NOT_ACCEPTED = "not_accepted"


class InvalidTransition(ValueError):
    """Raised when a command attempts an invalid lifecycle transition."""


class RoutingAlreadyActive(ValueError):
    """Raised when a complaint already has an active routing decision."""


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: UUID
    event_type: str
    aggregate_id: UUID
    from_status: ComplaintStatus | None
    to_status: ComplaintStatus
    actor_type: str
    actor_id: str
    policy_version: str
    correlation_id: str
    idempotency_key: str
    occurred_at: datetime


@dataclass(slots=True)
class ComplaintAggregate:
    complaint_id: UUID
    status: ComplaintStatus = ComplaintStatus.RECEIVED
    version: int = 0
    events: list[DomainEvent] = field(default_factory=list)
    _idempotency_keys: set[str] = field(default_factory=set, repr=False)

    _ALLOWED: dict[ComplaintStatus, frozenset[ComplaintStatus]] = field(
        default_factory=lambda: {
            ComplaintStatus.RECEIVED: frozenset(
                {ComplaintStatus.VERIFYING, ComplaintStatus.NOT_ACCEPTED}
            ),
            ComplaintStatus.VERIFYING: frozenset(
                {
                    ComplaintStatus.ROUTING_REVIEW,
                    ComplaintStatus.NEEDS_CLARIFICATION,
                    ComplaintStatus.NOT_ACCEPTED,
                }
            ),
            ComplaintStatus.ROUTING_REVIEW: frozenset(
                {ComplaintStatus.MAPPING_IN_PROGRESS, ComplaintStatus.SENT}
            ),
            ComplaintStatus.MAPPING_IN_PROGRESS: frozenset(
                {ComplaintStatus.ROUTING_REVIEW}
            ),
            ComplaintStatus.SENT: frozenset({ComplaintStatus.AWAITING_RESPONSE}),
            ComplaintStatus.AWAITING_RESPONSE: frozenset(
                {ComplaintStatus.ESCALATED, ComplaintStatus.FIX_REPORTED}
            ),
            ComplaintStatus.ESCALATED: frozenset(
                {ComplaintStatus.ESCALATED, ComplaintStatus.FIX_REPORTED}
            ),
            ComplaintStatus.FIX_REPORTED: frozenset(
                {ComplaintStatus.AWAITING_CITIZEN_CONFIRMATION}
            ),
            ComplaintStatus.AWAITING_CITIZEN_CONFIRMATION: frozenset(
                {ComplaintStatus.CLOSED, ComplaintStatus.REOPENED}
            ),
            ComplaintStatus.REOPENED: frozenset({ComplaintStatus.AWAITING_RESPONSE}),
            ComplaintStatus.NEEDS_CLARIFICATION: frozenset(
                {ComplaintStatus.VERIFYING}
            ),
            ComplaintStatus.NOT_ACCEPTED: frozenset(),
            ComplaintStatus.CLOSED: frozenset(),
        },
        repr=False,
    )

    @classmethod
    def receive(
        cls,
        complaint_id: UUID,
        *,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> "ComplaintAggregate":
        """Create a complaint in ``received`` state with its audit event."""

        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        aggregate = cls(complaint_id, status=ComplaintStatus.RECEIVED, version=1)
        aggregate._idempotency_keys.add(idempotency_key)
        aggregate.events.append(
            DomainEvent(
                event_id=uuid4(),
                event_type="complaint.received",
                aggregate_id=complaint_id,
                from_status=None,
                to_status=ComplaintStatus.RECEIVED,
                actor_type=actor_type,
                actor_id=actor_id,
                policy_version=policy_version,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                occurred_at=datetime.now(timezone.utc),
            )
        )
        return aggregate

    def transition(
        self,
        to_status: ComplaintStatus,
        *,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
        event_type: str | None = None,
        closure_proof_claim_id: UUID | None = None,
    ) -> DomainEvent | None:
        """Apply one idempotent, policy-versioned domain command."""

        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if idempotency_key in self._idempotency_keys:
            return None
        allowed = self._ALLOWED.get(self.status, frozenset())
        if to_status not in allowed:
            raise InvalidTransition(
                f"Cannot transition complaint from {self.status.value} to {to_status.value}"
            )
        if to_status == ComplaintStatus.FIX_REPORTED and closure_proof_claim_id is None:
            raise InvalidTransition("A fix report requires an accepted proof claim")

        previous = self.status
        self.status = to_status
        self.version += 1
        self._idempotency_keys.add(idempotency_key)
        event = DomainEvent(
            event_id=uuid4(),
            event_type=event_type or f"complaint.{to_status.value}",
            aggregate_id=self.complaint_id,
            from_status=previous,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            policy_version=policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            occurred_at=datetime.now(timezone.utc),
        )
        self.events.append(event)
        return event

    def activate_routing(
        self,
        *,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> DomainEvent | None:
        """Record a verified routing decision without changing lifecycle status."""

        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if idempotency_key in self._idempotency_keys:
            return None
        if self.status not in {
            ComplaintStatus.RECEIVED,
            ComplaintStatus.VERIFYING,
            ComplaintStatus.ROUTING_REVIEW,
            ComplaintStatus.MAPPING_IN_PROGRESS,
        }:
            raise InvalidTransition(
                f"Cannot activate routing while complaint is {self.status.value}"
            )

        self.version += 1
        self._idempotency_keys.add(idempotency_key)
        event = DomainEvent(
            event_id=uuid4(),
            event_type="complaint.routing_activated",
            aggregate_id=self.complaint_id,
            from_status=self.status,
            to_status=self.status,
            actor_type=actor_type,
            actor_id=actor_id,
            policy_version=policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            occurred_at=datetime.now(timezone.utc),
        )
        self.events.append(event)
        return event

    def record_disclosure_consent(
        self,
        *,
        actor_type: str,
        actor_id: str,
        policy_version: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> DomainEvent | None:
        """Record an auditable consent decision without changing lifecycle status."""

        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not policy_version.strip():
            raise ValueError("policy_version is required")
        if idempotency_key in self._idempotency_keys:
            return None

        self.version += 1
        self._idempotency_keys.add(idempotency_key)
        event = DomainEvent(
            event_id=uuid4(),
            event_type="complaint.disclosure_consented",
            aggregate_id=self.complaint_id,
            from_status=self.status,
            to_status=self.status,
            actor_type=actor_type,
            actor_id=actor_id,
            policy_version=policy_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            occurred_at=datetime.now(timezone.utc),
        )
        self.events.append(event)
        return event
