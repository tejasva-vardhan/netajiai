from __future__ import annotations

import pytest

from backend.app.application.evidence import EvidenceProviderUnavailable, UploadedPart
from backend.app.infrastructure.storage import S3ObjectStore


class RecordingS3Client:
    def create_multipart_upload(self, **kwargs):
        self.create_kwargs = kwargs
        return {"UploadId": "upload-1"}

    def complete_multipart_upload(self, **kwargs):
        self.complete_kwargs = kwargs


class FailingPresignClient:
    def generate_presigned_url(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("credentials unavailable")


def test_s3_multipart_completion_passes_server_validated_part_checksums():
    client = RecordingS3Client()
    store = S3ObjectStore("bucket", region="ap-south-1", client=client)

    session = store.create_multipart_upload(
        object_key="evidence/asset",
        content_type="image/jpeg",
        byte_size=10,
        sha256="a" * 64,
        part_size=5 * 1024 * 1024,
    )
    store.complete_multipart_upload(
        object_key="evidence/asset",
        upload_id=session.upload_id,
        parts=(
            UploadedPart(
                part_number=1,
                etag="etag-1",
                sha256="b" * 64,
                byte_size=5,
            ),
            UploadedPart(
                part_number=2,
                etag="etag-2",
                sha256="c" * 64,
                byte_size=5,
            ),
        ),
    )

    assert client.create_kwargs["ChecksumType"] == "COMPOSITE"
    assert client.complete_kwargs["ChecksumType"] == "COMPOSITE"
    assert client.complete_kwargs["MpuObjectSize"] == 10
    assert client.complete_kwargs["MultipartUpload"]["Parts"][0][
        "ChecksumSHA256"
    ]


def test_s3_upload_grant_failure_is_reported_as_provider_unavailable():
    store = S3ObjectStore("bucket", region="ap-south-1", client=FailingPresignClient())

    with pytest.raises(EvidenceProviderUnavailable, match="upload"):
        store.create_upload_grant(
            object_key="evidence/asset",
            content_type="image/jpeg",
            byte_size=10,
            sha256="a" * 64,
        )
