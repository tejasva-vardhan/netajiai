"""Grounded scheme-information service with a fail-closed answer policy."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

from backend.app.contracts.schemes import (
    SchemeAnswerResponse,
    SchemeIngestionRequest,
    SchemeApprovalResponse,
    SchemeReviewItem,
    SchemeReviewPage,
    SchemeReviewSource,
    SchemeSourceCitation,
)


@dataclass(frozen=True, slots=True)
class SchemeCandidate:
    answer_text: str
    sources: tuple[SchemeSourceCitation, ...]


class SchemeKnowledgeRepository(Protocol):
    def search(
        self,
        *,
        query: str,
        language: str | None,
        jurisdiction_code: str | None,
        now: datetime,
        limit: int,
    ) -> list[SchemeCandidate]: ...


class SchemeKnowledgeUnavailable(RuntimeError):
    """The reviewed scheme store could not be queried safely."""


class SchemeReviewRejected(ValueError):
    """A scheme submission or approval failed a review invariant."""


class SchemeReviewConflict(ValueError):
    """A scheme cannot be approved from its current review state."""


@dataclass(frozen=True, slots=True)
class SchemeApproval:
    scheme_id: UUID
    reviewed_by: str
    reviewed_at: datetime


@dataclass(frozen=True, slots=True)
class SchemeReviewSourceRow:
    source_id: UUID
    title: str
    publisher: str
    url: str
    document_hash: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class SchemeReviewRow:
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
    created_at: datetime
    updated_at: datetime
    sources: tuple[SchemeReviewSourceRow, ...]


class SchemeReviewRepository(Protocol):
    def stage(self, payload: SchemeIngestionRequest, *, now: datetime) -> UUID: ...

    def approve(
        self, scheme_id: UUID, *, reviewer_id: str, now: datetime
    ) -> SchemeApproval: ...

    def list_pending(
        self,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[SchemeReviewRow]: ...


class SchemeReviewCursorInvalid(ValueError):
    """The scheme review cursor cannot be safely decoded."""


class SchemeReviewService:
    """Stage source-backed records; approval is always an explicit human action."""

    def __init__(self, repository: SchemeReviewRepository) -> None:
        self._repository = repository

    def list_pending(self, *, limit: int, cursor: str | None) -> SchemeReviewPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = _decode_review_cursor(cursor) if cursor else None
        try:
            rows = self._repository.list_pending(limit=limit + 1, after=after)
        except Exception as exc:
            raise SchemeKnowledgeUnavailable(
                "Scheme review queue is temporarily unavailable"
            ) from exc
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        return SchemeReviewPage(
            items=[
                SchemeReviewItem(
                    scheme_id=row.scheme_id,
                    scheme_key=row.scheme_key,
                    language=row.language,
                    jurisdiction_code=row.jurisdiction_code,
                    title=row.title,
                    answer_text=row.answer_text,
                    eligibility_summary=row.eligibility_summary,
                    search_terms=row.search_terms,
                    version=row.version,
                    effective_from=row.effective_from,
                    effective_until=row.effective_until,
                    review_status="pending_review",
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    sources=[
                        SchemeReviewSource(
                            source_id=source.source_id,
                            title=source.title,
                            publisher=source.publisher,
                            url=source.url,
                            document_hash=source.document_hash,
                            retrieved_at=source.retrieved_at,
                        )
                        for source in row.sources
                    ],
                )
                for row in page_rows
            ],
            next_cursor=(
                _encode_review_cursor(page_rows[-1])
                if has_more and page_rows
                else None
            ),
        )

    def stage(
        self, payload: SchemeIngestionRequest, *, now: datetime
    ) -> UUID:
        if payload.effective_from and payload.effective_until:
            if payload.effective_until <= payload.effective_from:
                raise SchemeReviewRejected("effective_until must be after effective_from")
        for source in payload.sources:
            parsed = urlparse(source.url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise SchemeReviewRejected("Scheme sources must use HTTPS URLs")
            if source.retrieved_at > now:
                raise SchemeReviewRejected("A source cannot be retrieved in the future")
        try:
            return self._repository.stage(payload, now=now)
        except SchemeReviewRejected:
            raise
        except Exception as exc:
            raise SchemeKnowledgeUnavailable(
                "Scheme could not be staged safely"
            ) from exc

    def approve(
        self,
        scheme_id: UUID,
        *,
        reviewer_id: str,
        now: datetime,
    ) -> SchemeApprovalResponse:
        if not reviewer_id.strip():
            raise SchemeReviewRejected("A reviewer identity is required")
        try:
            approval = self._repository.approve(
                scheme_id, reviewer_id=reviewer_id, now=now
            )
        except (SchemeReviewRejected, SchemeReviewConflict):
            raise
        except KeyError as exc:
            raise SchemeReviewRejected("Scheme was not found") from exc
        except Exception as exc:
            raise SchemeKnowledgeUnavailable(
                "Scheme could not be approved safely"
            ) from exc
        return SchemeApprovalResponse(
            scheme_id=approval.scheme_id,
            status="approved",
            reviewed_by=approval.reviewed_by,
            reviewed_at=approval.reviewed_at,
        )


def _encode_review_cursor(row: SchemeReviewRow) -> str:
    payload = json.dumps(
        {"updated_at": row.updated_at.isoformat(), "scheme_id": str(row.scheme_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_review_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return datetime.fromisoformat(payload["updated_at"]), UUID(payload["scheme_id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SchemeReviewCursorInvalid("Invalid scheme review pagination cursor") from exc


class SchemeKnowledgeService:
    def __init__(self, repository: SchemeKnowledgeRepository) -> None:
        self._repository = repository

    def answer(
        self,
        *,
        query: str,
        language: str | None,
        jurisdiction_code: str | None,
        now: datetime,
    ) -> SchemeAnswerResponse:
        if not query.strip():
            return self._unavailable()
        try:
            candidates = self._repository.search(
                query=query.strip(),
                language=language,
                jurisdiction_code=jurisdiction_code,
                now=now,
                limit=3,
            )
        except Exception as exc:
            raise SchemeKnowledgeUnavailable(
                "Verified scheme information is temporarily unavailable"
            ) from exc
        if not candidates:
            return self._unavailable()
        candidate = candidates[0]
        if not candidate.sources:
            return self._unavailable()
        return SchemeAnswerResponse(
            status="answered",
            answer_text=candidate.answer_text,
            sources=list(candidate.sources),
        )

    @staticmethod
    def _unavailable() -> SchemeAnswerResponse:
        return SchemeAnswerResponse(
            status="unavailable",
            answer_text=(
                "Is yojana ke liye verified information abhi available nahi hai. "
                "Main eligibility ka anuman nahi lagaunga."
            ),
            sources=[],
        )
