"""Public HTTP response contracts for the first backend slice."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]
    service: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    version: str = Field(min_length=1)
    checks: dict[str, Literal["ok"]]


class DomainEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    aggregate_id: str
    occurred_at: datetime
