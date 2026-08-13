"""Contracts for grounded, source-cited scheme information."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SchemeAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    language: str | None = Field(default=None, min_length=2, max_length=40)
    jurisdiction_code: str | None = Field(default=None, max_length=120)


class SchemeSourceIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    publisher: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2_000)
    document_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retrieved_at: datetime


class SchemeIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,119}$")
    language: str = Field(min_length=2, max_length=40)
    jurisdiction_code: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    answer_text: str = Field(min_length=1, max_length=8_000)
    eligibility_summary: dict[str, object] = Field(default_factory=dict)
    search_terms: str = Field(min_length=1, max_length=1_000)
    version: str = Field(min_length=1, max_length=40)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    sources: list[SchemeSourceIngestionRequest] = Field(min_length=1, max_length=10)


class SchemeIngestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_id: UUID
    status: Literal["pending_review"]


class SchemeApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_id: UUID
    status: Literal["approved"]
    reviewed_by: str
    reviewed_at: datetime


class SchemeReviewSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    title: str = Field(min_length=1, max_length=255)
    publisher: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2_000)
    document_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retrieved_at: datetime


class SchemeReviewItem(BaseModel):
    """Bounded content-review projection for a staged scheme record."""

    model_config = ConfigDict(extra="forbid")

    scheme_id: UUID
    scheme_key: str
    language: str
    jurisdiction_code: str | None
    title: str
    answer_text: str
    eligibility_summary: dict[str, object]
    search_terms: str
    version: str
    effective_from: datetime | None
    effective_until: datetime | None
    review_status: Literal["pending_review"]
    created_at: datetime
    updated_at: datetime
    sources: list[SchemeReviewSource] = Field(min_length=1, max_length=10)


class SchemeReviewPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SchemeReviewItem] = Field(max_length=100)
    next_cursor: str | None = None


class SchemeSourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    title: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2_000)
    verified_at: datetime | None = None


class SchemeAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["answered", "unavailable"]
    answer_text: str = Field(min_length=1, max_length=4_000)
    sources: list[SchemeSourceCitation] = Field(default_factory=list, max_length=10)
