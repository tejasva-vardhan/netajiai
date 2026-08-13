"""Structured contracts exchanged with bounded AI handlers."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Intent = Literal["casual", "scheme", "filing", "status", "continuation"]


class IntentClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    confidence: float = Field(ge=0, le=1)
    reason_code: str = Field(min_length=1, max_length=80)


class ComplaintExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_type: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    language: str = Field(default="unknown", min_length=2, max_length=40)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)


class ComplaintDraftRequest(BaseModel):
    """Citizen text submitted for bounded, non-authoritative extraction."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10_000)
    language: str | None = Field(default=None, min_length=2, max_length=40)


class VoiceDraftRequest(BaseModel):
    """A verified audio asset is transcribed into a non-authoritative draft."""

    model_config = ConfigDict(extra="forbid")

    audio_asset_id: UUID
    language: str | None = Field(default=None, min_length=2, max_length=40)


class VoiceDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: ComplaintExtraction
    transcription_language: str = Field(min_length=2, max_length=40)
    transcription_confidence: float = Field(ge=0, le=1)
    transcription_provider: str = Field(min_length=1, max_length=120)
    transcription_model: str = Field(min_length=1, max_length=120)


class ApprovedResponse(BaseModel):
    """Response text generated only from approved workflow facts."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(min_length=2, max_length=40)
    source_event_ids: list[str] = Field(default_factory=list, max_length=50)
