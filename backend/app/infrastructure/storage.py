"""Object-storage adapters for direct evidence uploads."""

from __future__ import annotations

import base64
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any

from backend.app.application.evidence import (
    EvidenceProviderUnavailable,
    MultipartUploadSession,
    StoredObject,
    UploadGrant,
    UploadedPart,
)


class UnconfiguredObjectStore:
    def create_upload_grant(
        self, *, object_key: str, content_type: str, byte_size: int, sha256: str
    ) -> UploadGrant:
        del object_key, content_type, byte_size, sha256
        raise EvidenceProviderUnavailable("Object storage is not configured")

    def create_download_grant(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_seconds: int,
    ) -> UploadGrant:
        del object_key, content_type, expires_seconds
        raise EvidenceProviderUnavailable("Object storage is not configured")

    def head(self, object_key: str) -> StoredObject:
        raise EvidenceProviderUnavailable("Object storage is not configured")

    def read_bytes(self, object_key: str) -> bytes:
        del object_key
        raise EvidenceProviderUnavailable("Object storage is not configured")

    def create_multipart_upload(self, **kwargs: Any) -> MultipartUploadSession:
        del kwargs
        raise EvidenceProviderUnavailable("Object storage is not configured")

    def create_multipart_part_grant(self, **kwargs: Any) -> UploadGrant:
        del kwargs
        raise EvidenceProviderUnavailable("Object storage is not configured")

    def complete_multipart_upload(self, **kwargs: Any) -> None:
        del kwargs
        raise EvidenceProviderUnavailable("Object storage is not configured")

    def abort_multipart_upload(self, **kwargs: Any) -> None:
        del kwargs
        raise EvidenceProviderUnavailable("Object storage is not configured")


class S3ObjectStore:
    """S3 presigned PUT adapter; the API process never proxies media bytes."""

    def __init__(
        self,
        bucket: str,
        *,
        region: str,
        client: Any | None = None,
        endpoint_url: str = "",
        presign_endpoint_url: str = "",
        upload_ttl_seconds: int = 900,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket is required")
        self._bucket = bucket
        self._upload_ttl_seconds = upload_ttl_seconds
        self._presign_client: Any = client
        if client is None:
            import boto3  # type: ignore[import-untyped]

            client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=endpoint_url or None,
            )
        self._client = client
        if presign_endpoint_url and client is not None and presign_endpoint_url != endpoint_url:
            import boto3  # type: ignore[import-untyped]

            self._presign_client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=presign_endpoint_url,
            )
        elif self._presign_client is None:
            self._presign_client = client

    def create_upload_grant(
        self, *, object_key: str, content_type: str, byte_size: int, sha256: str
    ) -> UploadGrant:
        del byte_size
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._upload_ttl_seconds)
        # The metadata header is signed into the PUT request and lets the
        # completion worker compare the stored object with the claimed hash.
        try:
            url = self._presign_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                    "Metadata": {"sha256": sha256.lower()},
                    "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256)).decode("ascii"),
                },
                ExpiresIn=self._upload_ttl_seconds,
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise EvidenceProviderUnavailable(
                "Object storage could not grant an evidence upload"
            ) from exc
        return UploadGrant(
            url=url,
            method="PUT",
            headers={
                "Content-Type": content_type,
                "x-amz-meta-sha256": sha256.lower(),
                "x-amz-checksum-sha256": base64.b64encode(
                    bytes.fromhex(sha256)
                ).decode("ascii"),
            },
            expires_at=expires_at,
        )

    def create_download_grant(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_seconds: int,
    ) -> UploadGrant:
        if expires_seconds < 1:
            raise ValueError("Download-grant expiry must be positive")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
        try:
            url = self._presign_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "ResponseContentType": content_type,
                },
                ExpiresIn=expires_seconds,
                HttpMethod="GET",
            )
        except Exception as exc:
            raise EvidenceProviderUnavailable(
                "Object storage could not grant an evidence preview"
            ) from exc
        return UploadGrant(url=url, method="GET", headers={}, expires_at=expires_at)

    def head(self, object_key: str) -> StoredObject:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:
            error_response = getattr(exc, "response", {})
            error_code = error_response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error_code == 404:
                raise KeyError(object_key) from exc
            raise EvidenceProviderUnavailable("Object storage could not inspect the upload") from exc
        metadata = response.get("Metadata", {})
        sha256 = metadata.get("sha256", "")
        if not sha256:
            raise KeyError(f"Missing sha256 metadata for {object_key}")
        return StoredObject(
            object_key=object_key,
            content_type=response.get("ContentType", ""),
            byte_size=int(response["ContentLength"]),
            sha256=sha256,
        )

    def read_bytes(self, object_key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
            body = response["Body"].read()
        except Exception as exc:
            raise EvidenceProviderUnavailable("Object storage could not read the upload") from exc
        if not isinstance(body, bytes):
            raise EvidenceProviderUnavailable("Object storage returned an invalid upload")
        return body

    def create_multipart_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        byte_size: int,
        sha256: str,
        part_size: int,
    ) -> MultipartUploadSession:
        if part_size < 5 * 1024 * 1024:
            raise ValueError("S3 multipart parts must be at least 5 MiB")
        part_count = math.ceil(byte_size / part_size)
        if part_count > 10_000:
            raise ValueError("S3 multipart upload cannot exceed 10,000 parts")
        try:
            response = self._client.create_multipart_upload(
                Bucket=self._bucket,
                Key=object_key,
                ContentType=content_type,
                Metadata={"sha256": sha256.lower()},
                ChecksumAlgorithm="SHA256",
                ChecksumType="COMPOSITE",
            )
        except Exception as exc:
            raise EvidenceProviderUnavailable("Object storage could not start multipart upload") from exc
        upload_id = response.get("UploadId")
        if not isinstance(upload_id, str) or not upload_id:
            raise EvidenceProviderUnavailable("Object storage returned no multipart upload ID")
        return MultipartUploadSession(
            upload_id=upload_id,
            part_size=part_size,
            part_count=part_count,
        )

    def create_multipart_part_grant(
        self,
        *,
        object_key: str,
        upload_id: str,
        part_number: int,
    ) -> UploadGrant:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._upload_ttl_seconds)
        try:
            url = self._presign_client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=self._upload_ttl_seconds,
                HttpMethod="PUT",
            )
        except Exception as exc:
            raise EvidenceProviderUnavailable("Object storage could not grant a multipart part upload") from exc
        return UploadGrant(url=url, method="PUT", headers={}, expires_at=expires_at)

    def complete_multipart_upload(
        self,
        *,
        object_key: str,
        upload_id: str,
        parts: tuple[UploadedPart, ...],
    ) -> None:
        try:
            self._client.complete_multipart_upload(
                Bucket=self._bucket,
                Key=object_key,
                UploadId=upload_id,
                MultipartUpload={
                    "Parts": [
                        {
                            "PartNumber": part.part_number,
                            "ETag": part.etag,
                            "ChecksumSHA256": base64.b64encode(
                                bytes.fromhex(part.sha256)
                            ).decode("ascii"),
                        }
                        for part in parts
                    ]
                },
                ChecksumType="COMPOSITE",
                MpuObjectSize=sum(part.byte_size for part in parts),
            )
        except Exception as exc:
            raise EvidenceProviderUnavailable("Object storage could not complete multipart upload") from exc

    def abort_multipart_upload(self, *, object_key: str, upload_id: str) -> None:
        try:
            self._client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=object_key,
                UploadId=upload_id,
            )
        except Exception as exc:
            response = getattr(exc, "response", {})
            error = response.get("Error", {}) if isinstance(response, dict) else {}
            if error.get("Code") in {"NoSuchUpload", "404", 404}:
                return
            raise EvidenceProviderUnavailable("Object storage could not abort multipart upload") from exc


class InMemoryObjectStore:
    """Deterministic test adapter; never use it for user-visible production data."""

    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.multipart_sessions: dict[str, MultipartUploadSession] = {}
        self.multipart_completions: list[tuple[str, tuple[UploadedPart, ...]]] = []
        self.multipart_aborts: list[str] = []
        self.multipart_expected: dict[str, StoredObject] = {}

    def create_upload_grant(
        self, *, object_key: str, content_type: str, byte_size: int, sha256: str
    ) -> UploadGrant:
        del byte_size
        return UploadGrant(
            url=f"memory://{object_key}",
            method="PUT",
            headers={"Content-Type": content_type, "x-test-sha256": sha256.lower()},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )

    def head(self, object_key: str) -> StoredObject:
        try:
            return self.objects[object_key]
        except KeyError as exc:
            raise KeyError(object_key) from exc

    def read_bytes(self, object_key: str) -> bytes:
        del object_key
        raise EvidenceProviderUnavailable(
            "The in-memory object store has no media byte source"
        )

    def create_download_grant(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_seconds: int,
    ) -> UploadGrant:
        return UploadGrant(
            url=f"memory://preview/{object_key}",
            method="GET",
            headers={"Content-Type": content_type},
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )

    def seed(self, stored_object: StoredObject) -> None:
        self.objects[stored_object.object_key] = stored_object

    def create_multipart_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        byte_size: int,
        sha256: str,
        part_size: int,
    ) -> MultipartUploadSession:
        session = MultipartUploadSession(
            upload_id=str(uuid4()),
            part_size=part_size,
            part_count=math.ceil(byte_size / part_size),
        )
        self.multipart_sessions[object_key] = session
        self.multipart_expected[object_key] = StoredObject(
            object_key=object_key,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256.lower(),
        )
        return session

    def create_multipart_part_grant(
        self,
        *,
        object_key: str,
        upload_id: str,
        part_number: int,
    ) -> UploadGrant:
        return UploadGrant(
            url=f"memory://{object_key}/{upload_id}/{part_number}",
            method="PUT",
            headers={},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )

    def complete_multipart_upload(
        self,
        *,
        object_key: str,
        upload_id: str,
        parts: tuple[UploadedPart, ...],
    ) -> None:
        self.multipart_completions.append((upload_id, parts))
        if object_key not in self.objects:
            expected = self.multipart_expected.get(object_key)
            if expected is None:
                raise EvidenceProviderUnavailable("Unknown in-memory multipart upload")
            self.objects[object_key] = expected

    def abort_multipart_upload(self, *, object_key: str, upload_id: str) -> None:
        del object_key
        self.multipart_aborts.append(upload_id)
