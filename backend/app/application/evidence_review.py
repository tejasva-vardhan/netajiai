"""Human media-review boundary after automated inspection signals."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from backend.app.application.evidence import EvidenceProviderUnavailable, ObjectStore
from backend.app.contracts.evidence_review import (
    EvidenceReviewDecisionResponse,
    EvidenceReviewItem,
    EvidenceReviewPage,
)
from backend.app.contracts.identity import AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class EvidenceReviewRow:
    evidence_asset_id: UUID
    asset_type: str
    content_type: str
    byte_size: int
    captured_at: datetime
    received_at: datetime
    object_key: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceReviewResult:
    evidence_asset_id: UUID
    status: Literal["verified", "rejected"]
    reason_codes: tuple[str, ...]
    reviewed_at: datetime


class EvidenceReviewRepository(Protocol):
    def list_review_required(
        self,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[EvidenceReviewRow]: ...

    def record_review_decision(
        self,
        *,
        evidence_asset_id: UUID,
        reviewer_id: str,
        decision: Literal["approve", "reject"],
        reason_code: str,
        idempotency_key: str,
        now: datetime,
    ) -> EvidenceReviewResult: ...


class EvidenceReviewCursorInvalid(ValueError):
    """The review queue cursor cannot be safely decoded."""


class EvidenceReviewConflict(ValueError):
    """A review decision conflicts with an earlier decision."""


class EvidenceReviewService:
    _PREVIEW_TTL_SECONDS = 300

    def __init__(self, repository: EvidenceReviewRepository, object_store: ObjectStore) -> None:
        self._repository = repository
        self._object_store = object_store

    def list(self, *, limit: int, cursor: str | None) -> EvidenceReviewPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = _decode_cursor(cursor) if cursor else None
        rows = self._repository.list_review_required(limit=limit + 1, after=after)
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items: list[EvidenceReviewItem] = []
        for row in page_rows:
            try:
                grant = self._object_store.create_download_grant(
                    object_key=row.object_key,
                    content_type=row.content_type,
                    expires_seconds=self._PREVIEW_TTL_SECONDS,
                )
            except Exception as exc:
                raise EvidenceProviderUnavailable(
                    "Evidence preview storage is temporarily unavailable"
                ) from exc
            items.append(
                EvidenceReviewItem(
                    evidence_asset_id=row.evidence_asset_id,
                    asset_type=row.asset_type,  # type: ignore[arg-type]
                    content_type=row.content_type,
                    byte_size=row.byte_size,
                    captured_at=row.captured_at,
                    received_at=row.received_at,
                    reason_codes=row.reason_codes,
                    preview_url=grant.url,
                    preview_expires_at=grant.expires_at,
                )
            )
        next_cursor = _encode_cursor(page_rows[-1]) if has_more and page_rows else None
        return EvidenceReviewPage(items=items, next_cursor=next_cursor)

    def decide(
        self,
        principal: AuthenticatedPrincipal,
        *,
        evidence_asset_id: UUID,
        decision: Literal["approve", "reject"],
        reason_code: str,
        idempotency_key: str,
        now: datetime,
    ) -> EvidenceReviewDecisionResponse:
        if not principal.subject_ref.strip():
            raise EvidenceReviewConflict("Reviewer identity is required")
        if not idempotency_key.strip():
            raise EvidenceReviewConflict("Idempotency-Key is required")
        normalized_reason = reason_code.strip()
        if not normalized_reason:
            raise EvidenceReviewConflict("A review reason code is required")
        try:
            result = self._repository.record_review_decision(
                evidence_asset_id=evidence_asset_id,
                reviewer_id=principal.subject_ref,
                decision=decision,
                reason_code=normalized_reason,
                idempotency_key=idempotency_key,
                now=now,
            )
        except EvidenceReviewConflict:
            raise
        except Exception as exc:
            raise EvidenceReviewConflict("Evidence review could not be recorded") from exc
        return EvidenceReviewDecisionResponse(
            evidence_asset_id=result.evidence_asset_id,
            status=result.status,
            reason_codes=result.reason_codes,
            reviewed_at=result.reviewed_at,
        )


def _encode_cursor(row: EvidenceReviewRow) -> str:
    payload = json.dumps(
        {
            "received_at": row.received_at.isoformat(),
            "evidence_asset_id": str(row.evidence_asset_id),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        received_at = datetime.fromisoformat(payload["received_at"])
        asset_id = UUID(payload["evidence_asset_id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise EvidenceReviewCursorInvalid("Invalid evidence review cursor") from exc
    return received_at, asset_id
