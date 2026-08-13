"""Versioned evidence-capture and upload contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


AssetType = Literal["photo", "video", "audio"]
LocationSource = Literal["device_gps", "browser_gps", "network", "assisted_operator"]
EvidenceUploadStatus = Literal[
    "upload_pending", "uploaded", "review_required", "verified", "rejected"
]
EvidenceUploadMode = Literal["single", "multipart"]


class LocationCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=50_000)
    source: LocationSource


class CaptureSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_type: AssetType


class CaptureSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_token: str = Field(min_length=1, max_length=2_000)
    expires_at: datetime


class CreateEvidenceUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_type: AssetType
    content_type: str = Field(min_length=3, max_length=120)
    byte_size: int = Field(gt=0, le=50 * 1024 * 1024)
    client_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    capture_attestation: str = Field(min_length=1, max_length=2_000)
    location: LocationCapture | None = None


class EvidenceUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_asset_id: UUID
    status: EvidenceUploadStatus
    upload_mode: EvidenceUploadMode = "single"
    upload_url: str | None = None
    upload_method: Literal["PUT"] | None = None
    upload_headers: dict[str, str] = Field(default_factory=dict)
    upload_expires_at: datetime | None = None
    multipart_upload_id: str | None = None
    part_size: int | None = Field(default=None, gt=0)
    part_count: int | None = Field(default=None, gt=0)
    parts: list["EvidencePartUploadGrant"] = Field(default_factory=list, max_length=10_000)
    completed_parts: list[int] = Field(default_factory=list, max_length=10_000)


class EvidencePartUploadGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: int = Field(ge=1, le=10_000)
    upload_url: str = Field(min_length=1, max_length=4_000)
    upload_method: Literal["PUT"] = "PUT"
    upload_headers: dict[str, str] = Field(default_factory=dict)
    upload_expires_at: datetime


class CompleteEvidencePartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    etag: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    byte_size: int = Field(gt=0, le=5 * 1024 * 1024 * 1024)


class EvidencePartCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_asset_id: UUID
    part_number: int = Field(ge=1, le=10_000)
    accepted: bool
    etag: str


class EvidenceCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_asset_id: UUID
    status: Literal["uploaded", "review_required", "verified", "rejected"]
    reason_codes: tuple[str, ...] = ()
