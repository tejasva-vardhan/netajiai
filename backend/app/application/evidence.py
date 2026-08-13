"""Evidence upload and verification use case.

The API never receives a file body. It issues a short-lived object-storage
grant, records capture provenance, and verifies the uploaded object before a
complaint can reference it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, cast
from uuid import UUID, uuid4

from backend.app.contracts.evidence import (
    CompleteEvidencePartRequest,
    CreateEvidenceUploadRequest,
    EvidenceCompletionResponse,
    EvidencePartCompletionResponse,
    EvidencePartUploadGrant,
    EvidenceUploadMode,
    EvidenceUploadStatus,
    EvidenceUploadResponse,
)
from backend.app.contracts.identity import AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class CaptureAttestation:
    capture_source: str
    device_captured_at: datetime
    attestation_hash: str


@dataclass(frozen=True, slots=True)
class CaptureSession:
    token: str
    expires_at: datetime


class CaptureSessionIssuer(Protocol):
    def issue(
        self, *, citizen_id: str, asset_type: str, idempotency_key: str
    ) -> CaptureSession: ...


@dataclass(frozen=True, slots=True)
class LocationMetadata:
    latitude: float
    longitude: float
    accuracy_m: float
    source: str
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceAsset:
    evidence_asset_id: UUID
    citizen_id: str
    asset_type: str
    content_type: str
    byte_size: int
    client_sha256: str
    object_key: str
    status: str
    capture_source: str
    device_captured_at: datetime
    location_sample_id: UUID | None
    upload_mode: str = "single"
    multipart_upload_id: str | None = None
    part_size: int | None = None
    part_count: int | None = None
    multipart_cleanup_claimed_at: datetime | None = None
    uploaded_at: datetime | None = None
    verified_at: datetime | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UploadGrant:
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MultipartUploadSession:
    upload_id: str
    part_size: int
    part_count: int


@dataclass(frozen=True, slots=True)
class MultipartPartGrant:
    part_number: int
    grant: UploadGrant


@dataclass(frozen=True, slots=True)
class UploadedPart:
    part_number: int
    etag: str
    sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    content_type: str
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class InspectionResult:
    accepted: bool
    reason_codes: tuple[str, ...] = ()
    review_required: bool = False


class CaptureAttestationVerifier(Protocol):
    def verify(
        self, token: str, asset_type: str, citizen_id: str, idempotency_key: str
    ) -> CaptureAttestation: ...


class ObjectStore(Protocol):
    def create_upload_grant(
        self, *, object_key: str, content_type: str, byte_size: int, sha256: str
    ) -> UploadGrant: ...

    def head(self, object_key: str) -> StoredObject: ...

    def create_multipart_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        byte_size: int,
        sha256: str,
        part_size: int,
    ) -> MultipartUploadSession: ...

    def create_multipart_part_grant(
        self,
        *,
        object_key: str,
        upload_id: str,
        part_number: int,
    ) -> UploadGrant: ...

    def complete_multipart_upload(
        self,
        *,
        object_key: str,
        upload_id: str,
        parts: tuple[UploadedPart, ...],
    ) -> None: ...

    def abort_multipart_upload(self, *, object_key: str, upload_id: str) -> None: ...

    def create_download_grant(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_seconds: int,
    ) -> UploadGrant: ...


class MediaInspector(Protocol):
    def inspect(self, stored_object: StoredObject, asset: EvidenceAsset) -> InspectionResult: ...


class EvidenceMetadataRepository(Protocol):
    def find_by_creation_key(
        self, citizen_id: str, idempotency_key: str
    ) -> EvidenceAsset | None: ...

    def find_creation_request_fingerprint(
        self, citizen_id: str, idempotency_key: str
    ) -> str | None: ...

    def find_owned(self, citizen_id: str, evidence_asset_id: UUID) -> EvidenceAsset | None: ...

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
    ) -> EvidenceAsset: ...

    def mark_uploaded(
        self, evidence_asset_id: UUID, *, uploaded_at: datetime
    ) -> EvidenceAsset: ...

    def mark_verified(
        self,
        evidence_asset_id: UUID,
        *,
        verified_at: datetime,
        reason_codes: tuple[str, ...],
    ) -> EvidenceAsset: ...

    def mark_rejected(
        self,
        evidence_asset_id: UUID,
        *,
        reason_codes: tuple[str, ...],
        rejected_at: datetime,
    ) -> EvidenceAsset: ...

    def mark_review_required(
        self,
        evidence_asset_id: UUID,
        *,
        reason_codes: tuple[str, ...],
        review_required_at: datetime,
    ) -> EvidenceAsset: ...

    def find_uploaded_part(
        self, evidence_asset_id: UUID, part_number: int
    ) -> UploadedPart | None: ...

    def list_uploaded_parts(self, evidence_asset_id: UUID) -> tuple[UploadedPart, ...]: ...

    def record_uploaded_part(
        self,
        evidence_asset_id: UUID,
        *,
        part_number: int,
        etag: str,
        sha256: str,
        byte_size: int,
        now: datetime,
    ) -> UploadedPart: ...

    def claim_abandoned_multipart_uploads(
        self,
        *,
        before: datetime,
        now: datetime,
        retry_after: datetime,
        limit: int,
    ) -> tuple[EvidenceAsset, ...]: ...

    def mark_multipart_cleanup_complete(
        self, evidence_asset_id: UUID, *, cleaned_at: datetime
    ) -> EvidenceAsset: ...

    def record_multipart_cleanup_failure(
        self,
        evidence_asset_id: UUID,
        *,
        failed_at: datetime,
        error_type: str,
    ) -> EvidenceAsset: ...


class EvidenceCaptureRejected(ValueError):
    """Raised when a capture attestation or uploaded object is unacceptable."""


class EvidenceAssetNotFound(LookupError):
    """Raised when an asset is not owned by the authenticated citizen."""


class EvidenceProviderUnavailable(RuntimeError):
    """Raised when a required production evidence adapter is not configured."""


class EvidenceIdempotencyConflict(ValueError):
    """Raised when an upload key is reused for different metadata."""


class MultipartCleanupInProgress(RuntimeError):
    """Raised when cleanup has claimed a multipart asset before aborting it."""


class MultipartPartReceiptConflict(RuntimeError):
    """Raised when a retry presents different metadata for an acknowledged part."""


def _request_fingerprint(request: CreateEvidenceUploadRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceUploadService:
    _MULTIPART_THRESHOLD_BYTES = 10 * 1024 * 1024
    _MULTIPART_PART_SIZE = 5 * 1024 * 1024
    def __init__(
        self,
        repository: EvidenceMetadataRepository,
        capture_verifier: CaptureAttestationVerifier,
        object_store: ObjectStore,
        media_inspector: MediaInspector,
        *,
        browser_capture_review_required: bool = True,
    ) -> None:
        self._repository = repository
        self._capture_verifier = capture_verifier
        self._object_store = object_store
        self._media_inspector = media_inspector
        self._browser_capture_review_required = browser_capture_review_required

    def create_upload(
        self,
        principal: AuthenticatedPrincipal,
        request: CreateEvidenceUploadRequest,
        *,
        idempotency_key: str,
    ) -> EvidenceUploadResponse:
        if not principal.subject_ref.strip():
            raise EvidenceCaptureRejected("Authenticated citizen is required")
        if not idempotency_key.strip():
            raise EvidenceCaptureRejected("Idempotency-Key is required")
        if request.asset_type in {"photo", "video"} and request.location is None:
            raise EvidenceCaptureRejected("Photo and video require captured location")
        if (
            request.asset_type in {"photo", "video"}
            and request.location is not None
            and request.location.source not in {"device_gps", "browser_gps"}
        ):
            raise EvidenceCaptureRejected("Verified photo and video require captured GPS")
        allowed_types = {
            "photo": {"image/jpeg", "image/png", "image/webp"},
            "video": {"video/mp4", "video/webm", "video/quicktime"},
            "audio": {"audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/webm"},
        }
        if request.content_type.lower() not in allowed_types[request.asset_type]:
            raise EvidenceCaptureRejected("Content type is not allowed for this asset")

        request_fingerprint = _request_fingerprint(request)

        existing = self._repository.find_by_creation_key(
            principal.subject_ref, idempotency_key
        )
        if existing is not None:
            stored_fingerprint = self._repository.find_creation_request_fingerprint(
                principal.subject_ref, idempotency_key
            )
            if stored_fingerprint != request_fingerprint:
                raise EvidenceIdempotencyConflict(
                    "Evidence idempotency key belongs to another request"
                )
            return self._response_with_grant(existing)

        attestation = self._capture_verifier.verify(
            request.capture_attestation,
            request.asset_type,
            principal.subject_ref,
            idempotency_key,
        )
        browser_capture = attestation.capture_source.startswith("browser_")
        if request.location is not None:
            if browser_capture and request.location.source != "browser_gps":
                raise EvidenceCaptureRejected("Browser capture requires browser GPS")
            if not browser_capture and request.location.source == "browser_gps":
                raise EvidenceCaptureRejected("Browser GPS requires browser capture attestation")
        location = (
            LocationMetadata(
                latitude=request.location.latitude,
                longitude=request.location.longitude,
                accuracy_m=request.location.accuracy_m,
                source=request.location.source,
                captured_at=attestation.device_captured_at,
            )
            if request.location is not None
            else None
        )
        evidence_asset_id = uuid4()
        owner_hash = hashlib.sha256(principal.subject_ref.encode("utf-8")).hexdigest()[:16]
        object_key = f"evidence/{owner_hash}/{evidence_asset_id}"
        multipart: MultipartUploadSession | None = None
        if request.byte_size >= self._MULTIPART_THRESHOLD_BYTES:
            multipart = self._object_store.create_multipart_upload(
                object_key=object_key,
                content_type=request.content_type,
                byte_size=request.byte_size,
                sha256=request.client_sha256.lower(),
                part_size=self._MULTIPART_PART_SIZE,
            )
        # Generate the grant before committing metadata; a provider failure
        # cannot leave a user-visible pending row with no upload path.
        grant = None
        part_grants: tuple[MultipartPartGrant, ...] = ()
        try:
            grant = (
                self._object_store.create_upload_grant(
                    object_key=object_key,
                    content_type=request.content_type,
                    byte_size=request.byte_size,
                    sha256=request.client_sha256.lower(),
                )
                if multipart is None
                else None
            )
            if multipart is not None:
                part_grants = tuple(
                    MultipartPartGrant(
                        part_number=part_number,
                        grant=self._object_store.create_multipart_part_grant(
                            object_key=object_key,
                            upload_id=multipart.upload_id,
                            part_number=part_number,
                        ),
                    )
                    for part_number in range(1, multipart.part_count + 1)
                )
        except Exception:
            if multipart is not None:
                self._object_store.abort_multipart_upload(
                    object_key=object_key, upload_id=multipart.upload_id
                )
            raise
        try:
            asset = self._repository.create_pending(
                evidence_asset_id=evidence_asset_id,
                citizen_id=principal.subject_ref,
                creation_idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                request=request,
                object_key=object_key,
                attestation=attestation,
                location=location,
                now=datetime.now(timezone.utc),
                upload_mode="multipart" if multipart is not None else "single",
                multipart_upload_id=multipart.upload_id if multipart else None,
                part_size=multipart.part_size if multipart else None,
                part_count=multipart.part_count if multipart else None,
            )
        except Exception:
            if multipart is not None:
                self._object_store.abort_multipart_upload(
                    object_key=object_key, upload_id=multipart.upload_id
                )
            raise
        if asset.evidence_asset_id != evidence_asset_id:
            if multipart is not None:
                self._object_store.abort_multipart_upload(
                    object_key=object_key, upload_id=multipart.upload_id
                )
            return self._response_with_grant(asset)
        return self._response(asset, grant, part_grants)

    def complete_part(
        self,
        principal: AuthenticatedPrincipal,
        evidence_asset_id: UUID,
        part_number: int,
        request: CompleteEvidencePartRequest,
    ) -> EvidencePartCompletionResponse:
        asset = self._repository.find_owned(principal.subject_ref, evidence_asset_id)
        if asset is None:
            raise EvidenceAssetNotFound("Evidence asset was not found")
        if asset.upload_mode != "multipart" or not asset.part_count or not asset.part_size:
            raise EvidenceCaptureRejected("This evidence asset does not use multipart upload")
        if asset.multipart_cleanup_claimed_at is not None:
            raise EvidenceCaptureRejected("Multipart upload cleanup is in progress")
        if asset.status != "upload_pending":
            raise EvidenceCaptureRejected("Multipart parts cannot be changed after upload completion")
        if part_number < 1 or part_number > asset.part_count:
            raise EvidenceCaptureRejected("Multipart part number is out of range")
        if part_number < asset.part_count and request.byte_size != asset.part_size:
            raise EvidenceCaptureRejected("Non-final multipart parts must use the configured part size")
        if part_number == asset.part_count and request.byte_size > asset.part_size:
            raise EvidenceCaptureRejected("Final multipart part exceeds the configured part size")
        existing = self._repository.find_uploaded_part(evidence_asset_id, part_number)
        if existing is not None:
            if (
                existing.etag != request.etag
                or existing.sha256.lower() != request.sha256.lower()
                or existing.byte_size != request.byte_size
            ):
                raise EvidenceCaptureRejected("Multipart part receipt conflicts with an earlier retry")
            return EvidencePartCompletionResponse(
                evidence_asset_id=evidence_asset_id,
                part_number=part_number,
                accepted=True,
                etag=existing.etag,
            )
        try:
            recorded = self._repository.record_uploaded_part(
                evidence_asset_id,
                part_number=part_number,
                etag=request.etag,
                sha256=request.sha256.lower(),
                byte_size=request.byte_size,
                now=datetime.now(timezone.utc),
            )
        except MultipartCleanupInProgress as exc:
            raise EvidenceCaptureRejected("Multipart upload cleanup is in progress") from exc
        except MultipartPartReceiptConflict as exc:
            raise EvidenceCaptureRejected(
                "Multipart part receipt conflicts with an earlier retry"
            ) from exc
        return EvidencePartCompletionResponse(
            evidence_asset_id=evidence_asset_id,
            part_number=part_number,
            accepted=True,
            etag=recorded.etag,
        )

    def complete_upload(
        self,
        principal: AuthenticatedPrincipal,
        evidence_asset_id: UUID,
    ) -> EvidenceCompletionResponse:
        asset = self._repository.find_owned(principal.subject_ref, evidence_asset_id)
        if asset is None:
            raise EvidenceAssetNotFound("Evidence asset was not found")
        if asset.status == "verified":
            return EvidenceCompletionResponse(
                evidence_asset_id=asset.evidence_asset_id, status="verified"
            )
        if asset.status == "review_required":
            return EvidenceCompletionResponse(
                evidence_asset_id=asset.evidence_asset_id,
                status="review_required",
                reason_codes=asset.reason_codes or ("review_pending",),
            )
        if asset.status == "rejected":
            return EvidenceCompletionResponse(
                evidence_asset_id=asset.evidence_asset_id,
                status="rejected",
                reason_codes=asset.reason_codes or ("evidence_rejected",),
            )
        if asset.multipart_cleanup_claimed_at is not None:
            raise EvidenceCaptureRejected("Multipart upload cleanup is in progress")
        if asset.upload_mode == "multipart":
            if (
                not asset.multipart_upload_id
                or not asset.part_count
                or not asset.part_size
            ):
                raise EvidenceCaptureRejected("Multipart upload metadata is incomplete")
            parts = self._repository.list_uploaded_parts(evidence_asset_id)
            if len(parts) != asset.part_count or tuple(
                part.part_number for part in parts
            ) != tuple(range(1, asset.part_count + 1)):
                return EvidenceCompletionResponse(
                    evidence_asset_id=evidence_asset_id,
                    status="uploaded",
                    reason_codes=("multipart_parts_incomplete",),
                )
            try:
                self._object_store.head(asset.object_key)
            except KeyError:
                self._object_store.complete_multipart_upload(
                    object_key=asset.object_key,
                    upload_id=asset.multipart_upload_id,
                    parts=parts,
                )
        try:
            stored = self._object_store.head(asset.object_key)
        except KeyError as exc:
            raise EvidenceCaptureRejected("Uploaded object was not found") from exc
        if (
            stored.byte_size != asset.byte_size
            or stored.content_type != asset.content_type
            or stored.sha256.lower() != asset.client_sha256.lower()
        ):
            reasons = ("object_integrity_mismatch",)
            self._repository.mark_rejected(
                evidence_asset_id,
                reason_codes=reasons,
                rejected_at=datetime.now(timezone.utc),
            )
            return EvidenceCompletionResponse(
                evidence_asset_id=evidence_asset_id, status="rejected", reason_codes=reasons
            )

        uploaded = self._repository.mark_uploaded(
            evidence_asset_id, uploaded_at=datetime.now(timezone.utc)
        )
        inspection = self._media_inspector.inspect(stored, uploaded)
        reason_codes = inspection.reason_codes or ("media_verification_failed",)
        browser_capture = uploaded.capture_source.startswith("browser_")
        if inspection.review_required or (
            browser_capture and inspection.accepted and self._browser_capture_review_required
        ):
            if browser_capture and "browser_capture_review" not in reason_codes:
                reason_codes = (*reason_codes, "browser_capture_review")
            self._repository.mark_review_required(
                evidence_asset_id,
                reason_codes=reason_codes,
                review_required_at=datetime.now(timezone.utc),
            )
            return EvidenceCompletionResponse(
                evidence_asset_id=evidence_asset_id,
                status="review_required",
                reason_codes=reason_codes,
            )
        if not inspection.accepted:
            self._repository.mark_rejected(
                evidence_asset_id,
                reason_codes=reason_codes,
                rejected_at=datetime.now(timezone.utc),
            )
            return EvidenceCompletionResponse(
                evidence_asset_id=evidence_asset_id,
                status="rejected",
                reason_codes=reason_codes,
            )
        verified = self._repository.mark_verified(
            evidence_asset_id,
            verified_at=datetime.now(timezone.utc),
            reason_codes=inspection.reason_codes,
        )
        return EvidenceCompletionResponse(
            evidence_asset_id=verified.evidence_asset_id,
            status="verified",
            reason_codes=inspection.reason_codes,
        )


    def _response_with_grant(self, asset: EvidenceAsset) -> EvidenceUploadResponse:
        if asset.status != "upload_pending":
            return self._response(asset, None)
        if asset.upload_mode == "multipart":
            if not asset.multipart_upload_id or not asset.part_count:
                raise EvidenceProviderUnavailable("Multipart upload metadata is incomplete")
            part_grants = tuple(
                MultipartPartGrant(
                    part_number=part_number,
                    grant=self._object_store.create_multipart_part_grant(
                        object_key=asset.object_key,
                        upload_id=asset.multipart_upload_id,
                        part_number=part_number,
                    ),
                )
                for part_number in range(1, asset.part_count + 1)
            )
            completed_parts = tuple(
                part.part_number
                for part in self._repository.list_uploaded_parts(asset.evidence_asset_id)
            )
            return self._response(asset, None, part_grants, completed_parts)
        grant = self._object_store.create_upload_grant(
            object_key=asset.object_key,
            content_type=asset.content_type,
            byte_size=asset.byte_size,
            sha256=asset.client_sha256,
        )
        return self._response(asset, grant)

    @staticmethod
    def _response(
        asset: EvidenceAsset,
        grant: UploadGrant | None,
        part_grants: tuple[MultipartPartGrant, ...] = (),
        completed_parts: tuple[int, ...] = (),
    ) -> EvidenceUploadResponse:
        return EvidenceUploadResponse(
            evidence_asset_id=asset.evidence_asset_id,
            status=cast(EvidenceUploadStatus, asset.status),
            upload_mode=cast(EvidenceUploadMode, asset.upload_mode),
            upload_url=grant.url if grant else None,
            upload_method="PUT" if grant else None,
            upload_headers=grant.headers if grant else {},
            upload_expires_at=grant.expires_at if grant else None,
            multipart_upload_id=asset.multipart_upload_id,
            part_size=asset.part_size,
            part_count=asset.part_count,
            parts=[
                EvidencePartUploadGrant(
                    part_number=item.part_number,
                    upload_url=item.grant.url,
                    upload_method="PUT",
                    upload_headers=item.grant.headers,
                    upload_expires_at=item.grant.expires_at,
                )
                for item in part_grants
            ],
            completed_parts=list(completed_parts),
        )


@dataclass(frozen=True, slots=True)
class EvidenceCleanupResult:
    claimed: int
    cleaned: int
    failed: int


class EvidenceUploadCleanupService:
    """Reclaims stale multipart sessions without touching active uploads."""

    def __init__(
        self,
        repository: EvidenceMetadataRepository,
        object_store: ObjectStore,
    ) -> None:
        self._repository = repository
        self._object_store = object_store

    def cleanup_abandoned(
        self,
        *,
        now: datetime,
        max_age_seconds: float,
        retry_after_seconds: float,
        limit: int,
    ) -> EvidenceCleanupResult:
        if max_age_seconds <= 0 or retry_after_seconds <= 0 or limit < 1:
            raise ValueError("cleanup age, retry delay, and limit must be positive")
        candidates = self._repository.claim_abandoned_multipart_uploads(
            before=now - timedelta(seconds=max_age_seconds),
            now=now,
            retry_after=now - timedelta(seconds=retry_after_seconds),
            limit=limit,
        )
        cleaned = 0
        failed = 0
        for asset in candidates:
            if not asset.multipart_upload_id:
                failed += 1
                self._repository.record_multipart_cleanup_failure(
                    asset.evidence_asset_id,
                    failed_at=now,
                    error_type="missing_upload_id",
                )
                continue
            try:
                self._object_store.abort_multipart_upload(
                    object_key=asset.object_key,
                    upload_id=asset.multipart_upload_id,
                )
            except Exception as exc:
                failed += 1
                self._repository.record_multipart_cleanup_failure(
                    asset.evidence_asset_id,
                    failed_at=now,
                    error_type=type(exc).__name__,
                )
                continue
            self._repository.mark_multipart_cleanup_complete(
                asset.evidence_asset_id,
                cleaned_at=now,
            )
            cleaned += 1
        return EvidenceCleanupResult(
            claimed=len(candidates), cleaned=cleaned, failed=failed
        )
