"""Review-gated browser capture session adapter.

Browser APIs can capture camera, microphone, and location input, but they do
not provide the same device-integrity guarantees as an approved native
attestation provider. This adapter therefore issues short-lived,
subject/idempotency-bound sessions and labels resulting evidence as browser
capture. The evidence service keeps that evidence in ``review_required``
until a human or an approved media policy accepts it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.application.evidence import (
    CaptureAttestation,
    CaptureSession,
    CaptureSessionIssuer,
)


class BrowserCaptureSessionError(ValueError):
    """The browser capture session is invalid, expired, or mismatched."""


class BrowserCaptureSessionSigner(CaptureSessionIssuer):
    """Issue and verify bounded browser capture sessions with HMAC."""

    def __init__(self, secret: str, *, ttl_seconds: int = 300) -> None:
        secret_bytes = secret.encode("utf-8")
        if len(secret_bytes) < 32:
            raise ValueError("Browser capture session secret must be at least 32 bytes")
        if ttl_seconds < 1 or ttl_seconds > 900:
            raise ValueError("Browser capture session TTL must be between 1 and 900 seconds")
        self._secret = secret_bytes
        self._ttl_seconds = ttl_seconds

    def issue(
        self, *, citizen_id: str, asset_type: str, idempotency_key: str
    ) -> CaptureSession:
        self._validate_inputs(citizen_id, asset_type, idempotency_key)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        payload = {
            "version": 1,
            "subject": citizen_id,
            "asset_type": asset_type,
            "idempotency_key": idempotency_key,
            "nonce": secrets.token_urlsafe(18),
            "issued_at": int(now.timestamp()),
            "expires_at": int(expires_at.timestamp()),
        }
        return CaptureSession(
            token=self._encode(payload),
            expires_at=expires_at,
        )

    def verify(
        self,
        token: str,
        asset_type: str,
        citizen_id: str,
        idempotency_key: str,
    ) -> CaptureAttestation:
        self._validate_inputs(citizen_id, asset_type, idempotency_key)
        payload = self._decode(token)
        if (
            payload.get("subject") != citizen_id
            or payload.get("asset_type") != asset_type
            or payload.get("idempotency_key") != idempotency_key
        ):
            raise BrowserCaptureSessionError("Browser capture session does not match the request")
        issued_at = _positive_int(payload.get("issued_at"))
        expires_at = _positive_int(payload.get("expires_at"))
        now = int(datetime.now(timezone.utc).timestamp())
        if expires_at <= now or issued_at > now + 5:
            raise BrowserCaptureSessionError("Browser capture session is expired or invalid")
        source = {
            "photo": "browser_camera",
            "video": "browser_camera",
            "audio": "browser_microphone",
        }[asset_type]
        return CaptureAttestation(
            capture_source=source,
            device_captured_at=datetime.fromtimestamp(issued_at, tz=timezone.utc),
            attestation_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )

    def _encode(self, payload: dict[str, Any]) -> str:
        body = _b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signature = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
        return f"v1.{body}.{_b64url(signature)}"

    def _decode(self, token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "v1":
            raise BrowserCaptureSessionError("Browser capture session is invalid")
        body, supplied_signature = parts[1], parts[2]
        expected_signature = hmac.new(
            self._secret, body.encode("ascii"), hashlib.sha256
        ).digest()
        try:
            decoded_signature = base64.urlsafe_b64decode(
                supplied_signature + "=" * (-len(supplied_signature) % 4)
            )
            decoded_body = base64.urlsafe_b64decode(
                body + "=" * (-len(body) % 4)
            )
            payload = json.loads(decoded_body.decode("utf-8"))
        except (
            ValueError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise BrowserCaptureSessionError("Browser capture session is invalid") from exc
        if (
            _b64url(decoded_body) != body
            or _b64url(decoded_signature) != supplied_signature
            or not hmac.compare_digest(decoded_signature, expected_signature)
            or not isinstance(payload, dict)
        ):
            raise BrowserCaptureSessionError("Browser capture session is invalid")
        return payload

    @staticmethod
    def _validate_inputs(citizen_id: str, asset_type: str, idempotency_key: str) -> None:
        if not citizen_id.strip() or not idempotency_key.strip():
            raise BrowserCaptureSessionError("Authenticated citizen and idempotency key are required")
        if asset_type not in {"photo", "video", "audio"}:
            raise BrowserCaptureSessionError("Unsupported browser capture type")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BrowserCaptureSessionError("Browser capture session is invalid")
    return value
