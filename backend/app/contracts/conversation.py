"""Contracts for the single-voice, multi-handler conversation boundary."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.contracts.ai import ComplaintExtraction, Intent
from backend.app.contracts.schemes import SchemeSourceCitation


ConversationNextAction = Literal[
    "start_filing",
    "verify_identity",
    "provide_receipt",
    "scheme_answer",
    "scheme_unavailable",
    "continue_chat",
    "safety_refusal",
]


class ConversationContext(BaseModel):
    """Bounded context shared with language handlers, never a transcript."""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    language: str | None = Field(default=None, min_length=2, max_length=40)
    last_intent: Intent | None = None
    last_next_action: ConversationNextAction | None = None
    turn_count: int = Field(ge=0)
    previous_response_id: UUID | None = None
    complaint_draft: ComplaintExtraction | None = None


class ConversationTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10_000)
    language: str | None = Field(default=None, min_length=2, max_length=40)
    session_id: UUID | None = None

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be blank")
        return cleaned


class ConversationTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    response_id: UUID
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    response_text: str = Field(min_length=1, max_length=2_000)
    next_action: ConversationNextAction
    complaint_draft: ComplaintExtraction | None = None
    scheme_sources: list[SchemeSourceCitation] = Field(default_factory=list, max_length=10)
