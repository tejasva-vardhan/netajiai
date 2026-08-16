"""SQLAlchemy adapter for evidence metadata and location records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.application.evidence import (
    CaptureAttestation,
    EvidenceAsset,
    EvidenceIdempotencyConflict,
    EvidenceMetadataRepository,
    LocationMetadata,
    MultipartCleanupInProgress,
    MultipartPartReceiptConflict,
    UploadedPart,
)
from backend.app.application.evidence_review import (
    EvidenceReviewConflict,
    EvidenceReviewRepository,
    EvidenceReviewResult,
    EvidenceReviewRow,
)
from backend.app.contracts.evidence import CreateEvidenceUploadRequest
from backend.app.infrastructure.db import (
    EvidenceAssetRecord,
    EvidenceReviewEventRecord,
    EvidenceUploadPartRecord,
    LocationSampleRecord,
)


class SqlAlchemyEvidenceMetadataRepository(EvidenceMetadataRepository, EvidenceReviewRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_creation_key(
        self, citizen_id: str, idempotency_key: str
    ) -> EvidenceAsset | None:
        record = self._session.scalar(
            select(EvidenceAssetRecord).where(
                EvidenceAssetRecord.citizen_id == citizen_id,
                EvidenceAssetRecord.creation_idempotency_key == idempotency_key,
            )
        )
        return self._view(record) if record is not None else None

    def find_creation_request_fingerprint(
        self, citizen_id: str, idempotency_key: str
    ) -> str | None:
        return self._session.scalar(
            select(EvidenceAssetRecord.creation_request_fingerprint).where(
                EvidenceAssetRecord.citizen_id == citizen_id,
                EvidenceAssetRecord.creation_idempotency_key == idempotency_key,
            )
        )

    def find_owned(self, citizen_id: str, evidence_asset_id: UUID) -> EvidenceAsset | None:
        record = self._session.scalar(
            select(EvidenceAssetRecord).where(
                EvidenceAssetRecord.id == evidence_asset_id,
                EvidenceAssetRecord.citizen_id == citizen_id,
            )
        )
        return self._view(record) if record is not None else None

    def create_pending(
        self,
        *,
        evidence_asset_id: UUID,
        citizen_id: str,
        creation_idempotency_key: str,
        request_fingerprint: str,
        request: CreateEvidenceUploadRequest,
        object_key: str,
        attestation: CaptureAttestation,
        location: LocationMetadata | None,
        now: datetime,
        upload_mode: str = "single",
        multipart_upload_id: str | None = None,
        part_size: int | None = None,
        part_count: int | None = None,
    ) -> EvidenceAsset:
        location_id = None
        if location is not None:
            location_record = LocationSampleRecord(
                citizen_id=citizen_id,
                latitude=location.latitude,
                longitude=location.longitude,
                accuracy_m=location.accuracy_m,
                source=location.source,
                captured_at=location.captured_at,
                server_received_at=now,
            )
            self._session.add(location_record)
            self._session.flush()
            location_id = location_record.id
        record = EvidenceAssetRecord(
            id=evidence_asset_id,
            citizen_id=citizen_id,
            creation_idempotency_key=creation_idempotency_key,
            creation_request_fingerprint=request_fingerprint,
            asset_type=request.asset_type,
            content_type=request.content_type,
            byte_size=request.byte_size,
            client_sha256=request.client_sha256.lower(),
            object_key=object_key,
            status="upload_pending",
            capture_source=attestation.capture_source,
            capture_attestation_hash=attestation.attestation_hash,
            device_captured_at=attestation.device_captured_at,
            server_received_at=now,
            verification_signals={},
            location_sample_id=location_id,
            upload_mode=upload_mode,
            multipart_upload_id=multipart_upload_id,
            part_size=part_size,
            part_count=part_count,
            multipart_cleanup_attempts=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self.find_by_creation_key(citizen_id, creation_idempotency_key)
            if existing is None:
                raise
            stored_fingerprint = self.find_creation_request_fingerprint(
                citizen_id, creation_idempotency_key
            )
            if stored_fingerprint != request_fingerprint:
                raise EvidenceIdempotencyConflict(
                    "Evidence idempotency key belongs to another request"
                )
            return existing
        self._session.refresh(record)
        return self._view(record)

    def mark_uploaded(self, evidence_asset_id: UUID, *, uploaded_at: datetime) -> EvidenceAsset:
        record = self._required(evidence_asset_id)
        record.status = "uploaded"
        record.uploaded_at = uploaded_at
        record.updated_at = uploaded_at
        self._session.commit()
        return self._view(record)

    def mark_verified(
        self,
        evidence_asset_id: UUID,
        *,
        verified_at: datetime,
        reason_codes: tuple[str, ...],
    ) -> EvidenceAsset:
        record = self._required(evidence_asset_id)
        record.status = "verified"
        record.verified_at = verified_at
        record.verification_signals = {"reason_codes": list(reason_codes)}
        record.updated_at = verified_at
        self._session.commit()
        return self._view(record)

    def mark_rejected(
        self,
        evidence_asset_id: UUID,
        *,
        reason_codes: tuple[str, ...],
        rejected_at: datetime,
    ) -> EvidenceAsset:
        record = self._required(evidence_asset_id)
        record.status = "rejected"
        record.rejection_reason = ",".join(reason_codes)[:255]
        record.verification_signals = {"reason_codes": list(reason_codes)}
        record.updated_at = rejected_at
        self._session.commit()
        return self._view(record)

    def mark_review_required(
        self,
        evidence_asset_id: UUID,
        *,
        reason_codes: tuple[str, ...],
        review_required_at: datetime,
    ) -> EvidenceAsset:
        record = self._required(evidence_asset_id)
        record.status = "review_required"
        record.rejection_reason = None
        record.verification_signals = {"reason_codes": list(reason_codes)}
        record.updated_at = review_required_at
        self._session.commit()
        return self._view(record)

    def list_review_required(
        self,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[EvidenceReviewRow]:
        query = select(EvidenceAssetRecord).where(
            EvidenceAssetRecord.status == "review_required"
        )
        if after is not None:
            after_received_at, after_id = after
            query = query.where(
                or_(
                    EvidenceAssetRecord.server_received_at > after_received_at,
                    (
                        EvidenceAssetRecord.server_received_at == after_received_at
                    )
                    & (EvidenceAssetRecord.id > after_id),
                )
            )
        records = self._session.scalars(
            query.order_by(
                EvidenceAssetRecord.server_received_at.asc(), EvidenceAssetRecord.id.asc()
            ).limit(limit)
        )
        return [self._review_row(record) for record in records]

    def record_review_decision(
        self,
        *,
        evidence_asset_id: UUID,
        reviewer_id: str,
        decision: Literal["approve", "reject"],
        reason_code: str,
        idempotency_key: str,
        now: datetime,
    ) -> EvidenceReviewResult:
        record = self._session.get(
            EvidenceAssetRecord,
            evidence_asset_id,
            with_for_update=True,
            populate_existing=True,
        )
        if record is None:
            raise EvidenceReviewConflict("Evidence asset was not found")
        if record.status != "review_required":
            if record.review_idempotency_key == idempotency_key and record.reviewed_at is not None:
                replay = self._session.scalar(
                    select(EvidenceReviewEventRecord).where(
                        EvidenceReviewEventRecord.evidence_asset_id == evidence_asset_id,
                        EvidenceReviewEventRecord.idempotency_key == idempotency_key,
                    )
                )
                if (
                    replay is not None
                    and replay.reviewer_id == reviewer_id
                    and replay.decision == decision
                    and replay.reason_code == reason_code
                ):
                    return self._review_result(record)
            raise EvidenceReviewConflict("Evidence asset is no longer awaiting review")
        status = "verified" if decision == "approve" else "rejected"
        reason_codes = (
            ("human_review_approved", reason_code)
            if decision == "approve"
            else ("human_review_rejected", reason_code)
        )
        self._session.add(
            EvidenceReviewEventRecord(
                evidence_asset_id=evidence_asset_id,
                reviewer_id=reviewer_id,
                decision=decision,
                reason_code=reason_code,
                idempotency_key=idempotency_key,
                occurred_at=now,
            )
        )
        record.status = status
        record.reviewed_by = reviewer_id
        record.reviewed_at = now
        record.review_idempotency_key = idempotency_key
        record.rejection_reason = None if decision == "approve" else reason_code[:255]
        record.verified_at = now if decision == "approve" else None
        record.verification_signals = {"reason_codes": list(reason_codes)}
        record.updated_at = now
        self._session.commit()
        return EvidenceReviewResult(
            evidence_asset_id=evidence_asset_id,
            status=status,  # type: ignore[arg-type]
            reason_codes=reason_codes,
            reviewed_at=now,
        )

    @staticmethod
    def _review_row(record: EvidenceAssetRecord) -> EvidenceReviewRow:
        signals = record.verification_signals or {}
        reason_codes = tuple(
            value for value in signals.get("reason_codes", []) if isinstance(value, str)
        )
        return EvidenceReviewRow(
            evidence_asset_id=record.id,
            asset_type=record.asset_type,
            content_type=record.content_type,
            byte_size=record.byte_size,
            captured_at=record.device_captured_at,
            received_at=record.server_received_at,
            object_key=record.object_key,
            reason_codes=reason_codes,
        )

    @staticmethod
    def _review_result(record: EvidenceAssetRecord) -> EvidenceReviewResult:
        signals = record.verification_signals or {}
        reason_codes = tuple(
            value for value in signals.get("reason_codes", []) if isinstance(value, str)
        )
        reviewed_at = record.reviewed_at
        if reviewed_at is None:
            raise EvidenceReviewConflict("Evidence review timestamp is missing")
        if reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
        return EvidenceReviewResult(
            evidence_asset_id=record.id,
            status=record.status,  # type: ignore[arg-type]
            reason_codes=reason_codes,
            reviewed_at=reviewed_at,
        )

    def _required(self, evidence_asset_id: UUID) -> EvidenceAssetRecord:
        record = self._session.get(EvidenceAssetRecord, evidence_asset_id)
        if record is None:
            raise KeyError(evidence_asset_id)
        return record

    def find_uploaded_part(
        self, evidence_asset_id: UUID, part_number: int
    ) -> UploadedPart | None:
        record = self._session.get(
            EvidenceUploadPartRecord, (evidence_asset_id, part_number)
        )
        return self._part_view(record) if record is not None else None

    def list_uploaded_parts(self, evidence_asset_id: UUID) -> tuple[UploadedPart, ...]:
        records = self._session.scalars(
            select(EvidenceUploadPartRecord)
            .where(EvidenceUploadPartRecord.evidence_asset_id == evidence_asset_id)
            .order_by(EvidenceUploadPartRecord.part_number.asc())
        )
        return tuple(self._part_view(record) for record in records)

    def record_uploaded_part(
        self,
        evidence_asset_id: UUID,
        *,
        part_number: int,
        etag: str,
        sha256: str,
        byte_size: int,
        now: datetime,
    ) -> UploadedPart:
        asset_record = self._session.get(
            EvidenceAssetRecord,
            evidence_asset_id,
            with_for_update=True,
            populate_existing=True,
        )
        if asset_record is None:
            raise KeyError(evidence_asset_id)
        if asset_record.multipart_cleanup_claimed_at is not None:
            raise MultipartCleanupInProgress(evidence_asset_id)
        existing_record = self._session.get(
            EvidenceUploadPartRecord, (evidence_asset_id, part_number)
        )
        if existing_record is not None:
            if (
                existing_record.etag != etag
                or existing_record.sha256.lower() != sha256.lower()
                or existing_record.byte_size != byte_size
            ):
                raise MultipartPartReceiptConflict(evidence_asset_id)
            return self._part_view(existing_record)
        record = EvidenceUploadPartRecord(
            evidence_asset_id=evidence_asset_id,
            part_number=part_number,
            etag=etag,
            sha256=sha256.lower(),
            byte_size=byte_size,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        self._session.commit()
        self._session.refresh(record)
        return self._part_view(record)

    def claim_abandoned_multipart_uploads(
        self,
        *,
        before: datetime,
        now: datetime,
        retry_after: datetime,
        limit: int,
    ) -> tuple[EvidenceAsset, ...]:
        records = list(
            self._session.scalars(
                select(EvidenceAssetRecord)
                .where(
                    EvidenceAssetRecord.status == "upload_pending",
                    EvidenceAssetRecord.upload_mode == "multipart",
                    EvidenceAssetRecord.multipart_upload_id.is_not(None),
                    EvidenceAssetRecord.created_at <= before,
                    or_(
                        EvidenceAssetRecord.multipart_cleanup_claimed_at.is_(None),
                        EvidenceAssetRecord.multipart_cleanup_claimed_at <= retry_after,
                    ),
                )
                .order_by(EvidenceAssetRecord.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for record in records:
            record.multipart_cleanup_claimed_at = now
            record.multipart_cleanup_attempts += 1
            record.multipart_cleanup_last_error = None
            record.updated_at = now
        self._session.commit()
        return tuple(self._view(record) for record in records)

    def mark_multipart_cleanup_complete(
        self, evidence_asset_id: UUID, *, cleaned_at: datetime
    ) -> EvidenceAsset:
        record = self._required(evidence_asset_id)
        record.status = "rejected"
        record.rejection_reason = "multipart_upload_expired"
        record.verification_signals = {"reason_codes": ["multipart_upload_expired"]}
        record.multipart_cleanup_last_error = None
        record.updated_at = cleaned_at
        self._session.commit()
        return self._view(record)

    def record_multipart_cleanup_failure(
        self,
        evidence_asset_id: UUID,
        *,
        failed_at: datetime,
        error_type: str,
    ) -> EvidenceAsset:
        record = self._required(evidence_asset_id)
        record.multipart_cleanup_last_error = error_type[:120]
        record.multipart_cleanup_claimed_at = failed_at
        record.updated_at = failed_at
        self._session.commit()
        return self._view(record)

    @staticmethod
    def _view(record: EvidenceAssetRecord) -> EvidenceAsset:
        signals = record.verification_signals or {}
        reason_codes = tuple(
            value for value in signals.get("reason_codes", []) if isinstance(value, str)
        )
        return EvidenceAsset(
            evidence_asset_id=record.id,
            citizen_id=record.citizen_id,
            asset_type=record.asset_type,
            content_type=record.content_type,
            byte_size=record.byte_size,
            client_sha256=record.client_sha256,
            object_key=record.object_key,
            status=record.status,
            capture_source=record.capture_source,
            device_captured_at=record.device_captured_at,
            location_sample_id=record.location_sample_id,
            upload_mode=record.upload_mode,
            multipart_upload_id=record.multipart_upload_id,
            part_size=record.part_size,
            part_count=record.part_count,
            multipart_cleanup_claimed_at=record.multipart_cleanup_claimed_at,
            uploaded_at=record.uploaded_at,
            verified_at=record.verified_at,
            reason_codes=reason_codes,
        )

    @staticmethod
    def _part_view(record: EvidenceUploadPartRecord) -> UploadedPart:
        return UploadedPart(
            part_number=record.part_number,
            etag=record.etag,
            sha256=record.sha256,
            byte_size=record.byte_size,
        )
