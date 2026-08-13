"""Versioned queue-envelope contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.complaints import ComplaintStatus


class QueueEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    event_id: UUID
    topic: str = Field(min_length=1, max_length=120)
    message_key: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any]


class ComplaintLifecycleEvent(BaseModel):
    """Versioned payload carried by the complaint lifecycle queue topic."""

    model_config = ConfigDict(extra="forbid")

    complaint_id: UUID
    status: ComplaintStatus
    from_status: ComplaintStatus | None = None
    issue_type: str | None = Field(default=None, max_length=80)
    jurisdiction_code: str | None = Field(default=None, max_length=120)
    execution_zone_state: Literal["active", "mapping_in_progress"] | None = None
    routing_reason_code: str | None = Field(default=None, max_length=120)
    routing_snapshot_ref: str | None = Field(default=None, max_length=255)
    sla_policy_version: str | None = Field(default=None, max_length=120)
    response_timeout_seconds: int | None = Field(default=None, ge=1)
    post_escalation_timeout_seconds: int | None = Field(default=None, ge=1)
    evidence_count: int | None = Field(default=None, ge=0, le=10)
    issue_cluster_id: UUID | None = None
    issue_cluster_supporter_count: int | None = Field(default=None, ge=1)
    escalation_level: int | None = Field(default=None, ge=0, le=4)
    public_disclosure_eligible: bool | None = None
    disclosure_mode: Literal["verified_citizen", "public_name"] | None = None
    disclosure_policy_version: str | None = Field(default=None, max_length=120)
    closure_proof_claim_id: UUID | None = None
    citizen_resolution_outcome: Literal[
        "fully_solved", "partially_solved", "not_solved"
    ] | None = None
    request_fingerprint: str | None = Field(default=None, max_length=128)
