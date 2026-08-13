"""SQLAlchemy retrieval adapter for reviewed scheme records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.app.application.schemes import (
    SchemeApproval,
    SchemeCandidate,
    SchemeKnowledgeRepository,
    SchemeReviewRow,
    SchemeReviewSourceRow,
    SchemeReviewConflict,
    SchemeReviewRejected,
    SchemeReviewRepository,
)
from backend.app.contracts.schemes import SchemeIngestionRequest, SchemeSourceCitation
from backend.app.infrastructure.db import SchemeRecord, SchemeSourceRecord


class SqlAlchemySchemeKnowledgeRepository(SchemeKnowledgeRepository, SchemeReviewRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def search(
        self,
        *,
        query: str,
        language: str | None,
        jurisdiction_code: str | None,
        now: datetime,
        limit: int,
    ) -> list[SchemeCandidate]:
        needle = f"%{query.casefold()}%"
        conditions = [
            SchemeRecord.review_status == "approved",
            SchemeSourceRecord.review_status == "approved",
            or_(SchemeRecord.effective_from.is_(None), SchemeRecord.effective_from <= now),
            or_(SchemeRecord.effective_until.is_(None), SchemeRecord.effective_until > now),
            or_(
                SchemeRecord.title.ilike(needle),
                SchemeRecord.answer_text.ilike(needle),
                SchemeRecord.search_terms.ilike(needle),
            ),
        ]
        if language:
            conditions.append(SchemeRecord.language == language)
        if jurisdiction_code:
            conditions.append(
                or_(
                    SchemeRecord.jurisdiction_code == jurisdiction_code,
                    SchemeRecord.jurisdiction_code.is_(None),
                )
            )
        records = self._session.scalars(
            select(SchemeRecord)
            .join(SchemeSourceRecord)
            .options(selectinload(SchemeRecord.sources))
            .where(and_(*conditions))
            .order_by(SchemeRecord.reviewed_at.desc().nullslast(), SchemeRecord.updated_at.desc())
            .limit(limit)
        ).unique().all()
        return [
            SchemeCandidate(
                answer_text=record.answer_text,
                sources=tuple(
                    SchemeSourceCitation(
                        source_id=source.id,
                        title=source.title,
                        url=source.url,
                        verified_at=source.reviewed_at,
                    )
                    for source in record.sources
                    if source.review_status == "approved"
                ),
            )
            for record in records
        ]

    def stage(self, payload: SchemeIngestionRequest, *, now: datetime) -> UUID:
        scheme = SchemeRecord(
            scheme_key=payload.scheme_key,
            language=payload.language,
            jurisdiction_code=payload.jurisdiction_code,
            title=payload.title,
            answer_text=payload.answer_text,
            eligibility_summary=payload.eligibility_summary,
            search_terms=payload.search_terms,
            effective_from=payload.effective_from,
            effective_until=payload.effective_until,
            review_status="pending",
            version=payload.version,
            created_at=now,
            updated_at=now,
        )
        scheme.sources = [
            SchemeSourceRecord(
                title=source.title,
                publisher=source.publisher,
                url=source.url,
                document_hash=source.document_hash.lower(),
                retrieved_at=source.retrieved_at,
                review_status="pending",
                created_at=now,
            )
            for source in payload.sources
        ]
        self._session.add(scheme)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            existing = self._session.scalar(
                select(SchemeRecord)
                .options(selectinload(SchemeRecord.sources))
                .where(
                    SchemeRecord.scheme_key == payload.scheme_key,
                    SchemeRecord.language == payload.language,
                    SchemeRecord.version == payload.version,
                )
            )
            if existing is not None and self._matches_submission(existing, payload):
                return existing.id
            raise SchemeReviewRejected("Scheme version already exists or is invalid") from exc
        self._session.refresh(scheme)
        return scheme.id

    def approve(
        self, scheme_id: UUID, *, reviewer_id: str, now: datetime
    ) -> SchemeApproval:
        scheme = self._session.scalar(
            select(SchemeRecord)
            .options(selectinload(SchemeRecord.sources))
            .where(SchemeRecord.id == scheme_id)
            .with_for_update()
        )
        if scheme is None:
            raise KeyError(scheme_id)
        if scheme.review_status == "approved":
            if scheme.reviewed_by != reviewer_id:
                raise SchemeReviewConflict("Scheme is already approved by another reviewer")
            return SchemeApproval(
                scheme_id=scheme.id,
                reviewed_by=scheme.reviewed_by,
                reviewed_at=scheme.reviewed_at or now,
            )
        if scheme.review_status != "pending":
            raise SchemeReviewConflict("Scheme is not pending review")
        if not scheme.sources or any(
            source.review_status != "pending" for source in scheme.sources
        ):
            raise SchemeReviewRejected("Every scheme source must be pending review")
        scheme.review_status = "approved"
        scheme.reviewed_at = now
        scheme.reviewed_by = reviewer_id
        for source in scheme.sources:
            source.review_status = "approved"
            source.reviewed_at = now
            source.reviewed_by = reviewer_id
        scheme.updated_at = now
        self._session.commit()
        return SchemeApproval(
            scheme_id=scheme.id,
            reviewed_by=reviewer_id,
            reviewed_at=now,
        )

    def list_pending(
        self,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[SchemeReviewRow]:
        conditions = [SchemeRecord.review_status == "pending"]
        if after is not None:
            after_updated_at, after_scheme_id = after
            conditions.append(
                or_(
                    SchemeRecord.updated_at < after_updated_at,
                    and_(
                        SchemeRecord.updated_at == after_updated_at,
                        SchemeRecord.id < after_scheme_id,
                    ),
                )
            )
        records = self._session.scalars(
            select(SchemeRecord)
            .options(selectinload(SchemeRecord.sources))
            .where(and_(*conditions))
            .order_by(SchemeRecord.updated_at.desc(), SchemeRecord.id.desc())
            .limit(limit)
        ).unique().all()
        return [
            SchemeReviewRow(
                scheme_id=record.id,
                scheme_key=record.scheme_key,
                language=record.language,
                jurisdiction_code=record.jurisdiction_code,
                title=record.title,
                answer_text=record.answer_text,
                eligibility_summary=dict(record.eligibility_summary),
                search_terms=record.search_terms,
                version=record.version,
                effective_from=record.effective_from,
                effective_until=record.effective_until,
                created_at=record.created_at,
                updated_at=record.updated_at,
                sources=tuple(
                    SchemeReviewSourceRow(
                        source_id=source.id,
                        title=source.title,
                        publisher=source.publisher,
                        url=source.url,
                        document_hash=source.document_hash,
                        retrieved_at=source.retrieved_at,
                    )
                    for source in record.sources
                ),
            )
            for record in records
        ]

    def _matches_submission(self, record: SchemeRecord, payload: SchemeIngestionRequest) -> bool:
        existing_hashes = {source.document_hash.lower() for source in record.sources}
        submitted_hashes = {source.document_hash.lower() for source in payload.sources}
        return (
            record.title == payload.title
            and record.answer_text == payload.answer_text
            and record.search_terms == payload.search_terms
            and existing_hashes == submitted_hashes
        )
