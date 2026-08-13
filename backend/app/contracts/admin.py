"""Capability-protected, privacy-safe admin read contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminOverviewResponse(BaseModel):
    """Aggregate control-tower facts without citizen-level data."""

    model_config = ConfigDict(extra="forbid")

    total_complaints: int = Field(ge=0)
    status_counts: dict[str, int]
    execution_zone_counts: dict[str, int]
    escalated_count: int = Field(ge=0)
    mapping_in_progress_count: int = Field(ge=0)
    last_updated_at: datetime | None = None
