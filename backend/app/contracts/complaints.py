"""Versioned complaint command and response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.domain.complaints import ComplaintStatus
from backend.app.contracts.workflow_signals import CitizenResolutionOutcome


class CreateComplaintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_type: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=10_000)
    language: str = Field(min_length=2, max_length=40)
    jurisdiction_code: str | None = Field(default=None, max_length=120)
    evidence_asset_ids: list[UUID] = Field(min_length=1, max_length=10)
    citizen_confirmation: bool


class ComplaintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    complaint_id: UUID
    status: ComplaintStatus
    version: int
    execution_zone_state: str
    escalation_level: int = Field(ge=0, le=4)
    created_at: datetime
    tracking_token: str = ""
    issue_cluster_id: UUID | None = None
    supporter_count: int | None = Field(default=None, ge=1)


class PublicComplaintTrackingResponse(BaseModel):
    """Redacted tracking projection safe to return with a receipt token."""

    model_config = ConfigDict(extra="forbid")

    complaint_id: UUID
    status: ComplaintStatus
    version: int
    issue_type: str | None
    execution_zone_state: str
    escalation_level: int = Field(ge=0, le=4)
    created_at: datetime
    updated_at: datetime


class ComplaintTimelineItem(BaseModel):
    """Citizen-safe lifecycle evidence without private actor or payload data."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=120)
    reason_code: str | None = Field(default=None, max_length=80)
    from_status: ComplaintStatus | None = None
    status: ComplaintStatus
    escalation_level: int | None = Field(default=None, ge=0, le=4)
    occurred_at: datetime


class ComplaintTrackingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complaint_id: UUID
    status: ComplaintStatus
    version: int
    issue_type: str | None
    description: str | None
    jurisdiction_code: str | None
    execution_zone_state: str
    escalation_level: int = Field(ge=0, le=4)
    disclosure_mode: str
    last_citizen_resolution_outcome: CitizenResolutionOutcome | None = None
    issue_cluster_id: UUID | None = None
    supporter_count: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime
    timeline: list[ComplaintTimelineItem] = Field(default_factory=list)


class DisclosureConsentRequest(BaseModel):
    """Explicit, one-time citizen choice for case disclosure."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["verified_citizen", "public_name"]
    consent: Literal[True]


class DisclosureConsentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complaint_id: UUID
    disclosure_mode: Literal["verified_citizen", "public_name"]
    public_disclosure_eligible: bool
    policy_version: str
    consented_at: datetime


class AdminComplaintSummary(BaseModel):
    """Operational summary; deliberately excludes citizen identity and text."""

    model_config = ConfigDict(extra="forbid")

    complaint_id: UUID
    status: ComplaintStatus
    version: int
    issue_type: str | None
    execution_zone_state: str
    escalation_level: int = Field(ge=0, le=4)
    public_disclosure_eligible: bool
    jurisdiction_code: str | None
    issue_cluster_id: UUID | None = None
    supporter_count: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime


class AdminComplaintPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminComplaintSummary]
    next_cursor: str | None = None


class TransitionComplaintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: ComplaintStatus
