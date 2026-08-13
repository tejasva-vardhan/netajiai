"""Versioned read contracts for citizen-facing catalogues."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ComplaintCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    icon: str = Field(min_length=1, max_length=16)
    label_hi: str = Field(min_length=1, max_length=120)
    label_en: str = Field(min_length=1, max_length=120)
    spoken_hi: str = Field(min_length=1, max_length=160)


class ComplaintCategoryCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=80)
    items: list[ComplaintCategory] = Field(min_length=1, max_length=100)
