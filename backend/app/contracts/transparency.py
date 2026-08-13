"""Redacted public accountability projections."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PublicTransparencyResponse(BaseModel):
    """Aggregate facts suitable for a policy-approved public dashboard."""

    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(min_length=1, max_length=120)
    generated_at: datetime
    last_updated_at: datetime | None = None
    total_complaints: int = Field(ge=0)
    status_counts: dict[str, int]
    execution_zone_counts: dict[str, int]
    escalated_count: int = Field(ge=0)
    mapping_in_progress_count: int = Field(ge=0)
