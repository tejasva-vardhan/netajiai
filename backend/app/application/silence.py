"""Durable facts for deadlines that elapsed without a department response."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SilenceEvent:
    event_id: UUID
    complaint_id: UUID
    workflow_id: str
    reason_code: str
    status: str
    deadline_at: datetime
    observed_at: datetime
    escalation_level: int
    escalation_count: int
    policy_version: str
    request_fingerprint: str


class SilenceEventRepository(Protocol):
    def find_by_idempotency_key(
        self, complaint_id: UUID, idempotency_key: str
    ) -> SilenceEvent | None: ...

    def reserve(
        self,
        *,
        event_id: UUID,
        complaint_id: UUID,
        workflow_id: str,
        reason_code: str,
        status: str,
        deadline_at: datetime,
        observed_at: datetime,
        escalation_level: int,
        escalation_count: int,
        policy_version: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> SilenceEvent: ...


class SilenceEventConflict(ValueError):
    """The same idempotency key was reused for different deadline evidence."""


def silence_request_fingerprint(
    *,
    complaint_id: UUID,
    workflow_id: str,
    reason_code: str,
    status: str,
    deadline_at: datetime,
    escalation_level: int,
    escalation_count: int,
    policy_version: str,
) -> str:
    payload = "|".join(
        (
            str(complaint_id),
            workflow_id,
            reason_code,
            status,
            deadline_at.isoformat(),
            str(escalation_level),
            str(escalation_count),
            policy_version,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
