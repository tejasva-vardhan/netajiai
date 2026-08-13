"""Operator-only media review contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvidenceReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_asset_id: UUID
    asset_type: Literal["photo", "video", "audio"]
    content_type: str = Field(min_length=3, max_length=120)
    byte_size: int = Field(gt=0)
    captured_at: datetime
    received_at: datetime
    reason_codes: tuple[str, ...] = Field(max_length=20)
    preview_url: str = Field(min_length=1, max_length=4_000)
    preview_expires_at: datetime


class EvidenceReviewPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EvidenceReviewItem] = Field(max_length=100)
    next_cursor: str | None = None


class EvidenceReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason_code: str = Field(min_length=1, max_length=80)


class EvidenceReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_asset_id: UUID
    status: Literal["verified", "rejected"]
    reason_codes: tuple[str, ...] = Field(max_length=20)
    reviewed_at: datetime
