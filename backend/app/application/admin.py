"""Capability-protected admin read models."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.app.contracts.admin import AdminOverviewResponse
from backend.app.contracts.complaints import AdminComplaintPage, AdminComplaintSummary
from backend.app.domain.complaints import ComplaintStatus


@dataclass(frozen=True, slots=True)
class AdminComplaintRow:
    complaint_id: UUID
    status: str
    version: int
    issue_type: str | None
    execution_zone_state: str
    jurisdiction_code: str | None
    escalation_level: int
    public_disclosure_eligible: bool
    issue_cluster_id: UUID | None
    supporter_count: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AdminOverviewData:
    total_complaints: int
    status_counts: dict[str, int]
    execution_zone_counts: dict[str, int]
    escalated_count: int
    mapping_in_progress_count: int
    last_updated_at: datetime | None


class AdminComplaintRepository(Protocol):
    def list_complaints(
        self,
        *,
        status: str | None,
        execution_zone_state: str | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[AdminComplaintRow]: ...

    def summarize_complaints(self) -> AdminOverviewData: ...


class AdminCursorInvalid(ValueError):
    """The pagination cursor is malformed or cannot be safely interpreted."""


class AdminComplaintQueryService:
    def __init__(self, repository: AdminComplaintRepository) -> None:
        self._repository = repository

    def list(
        self,
        *,
        status: str | None,
        execution_zone_state: str | None,
        limit: int,
        cursor: str | None,
    ) -> AdminComplaintPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = _decode_cursor(cursor) if cursor else None
        rows = self._repository.list_complaints(
            status=status,
            execution_zone_state=execution_zone_state,
            limit=limit + 1,
            after=after,
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = _encode_cursor(page_rows[-1]) if has_more and page_rows else None
        return AdminComplaintPage(
            items=[
                AdminComplaintSummary(
                    complaint_id=row.complaint_id,
                    status=ComplaintStatus(row.status),
                    version=row.version,
                    issue_type=row.issue_type,
                    execution_zone_state=row.execution_zone_state,
                    jurisdiction_code=row.jurisdiction_code,
                    escalation_level=row.escalation_level,
                    public_disclosure_eligible=row.public_disclosure_eligible,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    issue_cluster_id=row.issue_cluster_id,
                    supporter_count=row.supporter_count,
                )
                for row in page_rows
            ],
            next_cursor=next_cursor,
        )

    def overview(self) -> AdminOverviewResponse:
        """Return aggregate facts suitable for an operator control tower."""

        data = self._repository.summarize_complaints()
        return AdminOverviewResponse(
            total_complaints=data.total_complaints,
            status_counts=dict(data.status_counts),
            execution_zone_counts=dict(data.execution_zone_counts),
            escalated_count=data.escalated_count,
            mapping_in_progress_count=data.mapping_in_progress_count,
            last_updated_at=data.last_updated_at,
        )


def _encode_cursor(row: AdminComplaintRow) -> str:
    payload = json.dumps(
        {"updated_at": row.updated_at.isoformat(), "complaint_id": str(row.complaint_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"])
        complaint_id = UUID(payload["complaint_id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AdminCursorInvalid("Invalid admin pagination cursor") from exc
    return updated_at, complaint_id
