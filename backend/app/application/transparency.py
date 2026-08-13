"""Policy-gated public accountability read service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.contracts.transparency import PublicTransparencyResponse


@dataclass(frozen=True, slots=True)
class PublicTransparencyData:
    total_complaints: int
    status_counts: dict[str, int]
    execution_zone_counts: dict[str, int]
    escalated_count: int
    mapping_in_progress_count: int
    last_updated_at: datetime | None


class PublicTransparencyRepository(Protocol):
    def summarize_public(self) -> PublicTransparencyData: ...


class PublicTransparencyService:
    def __init__(self, repository: PublicTransparencyRepository, *, policy_version: str) -> None:
        if not policy_version.strip():
            raise ValueError("Public transparency policy version is required")
        self._repository = repository
        self._policy_version = policy_version

    def get(self, *, now: datetime) -> PublicTransparencyResponse:
        data = self._repository.summarize_public()
        return PublicTransparencyResponse(
            policy_version=self._policy_version,
            generated_at=now,
            last_updated_at=data.last_updated_at,
            total_complaints=data.total_complaints,
            status_counts=dict(data.status_counts),
            execution_zone_counts=dict(data.execution_zone_counts),
            escalated_count=data.escalated_count,
            mapping_in_progress_count=data.mapping_in_progress_count,
        )
