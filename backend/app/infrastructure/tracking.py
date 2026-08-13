"""Opaque public receipt-token codec."""

from __future__ import annotations

import base64
import hashlib
import hmac
from uuid import UUID


class HmacPublicTrackingTokenCodec:
    """Sign a random UUID reference without storing a bearer token in plaintext."""

    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("Public tracking token secret must be at least 32 bytes")
        self._secret = secret.encode("utf-8")

    def encode(self, complaint_id: UUID) -> str:
        payload = complaint_id.bytes
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).rstrip(b"=").decode("ascii")

    def decode(self, token: str) -> UUID | None:
        if not token or len(token) > 100:
            return None
        try:
            padded = token.encode("ascii") + b"=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded)
        except (ValueError, UnicodeEncodeError):
            return None
        if len(raw) != 48:
            return None
        payload, signature = raw[:16], raw[16:]
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        return UUID(bytes=payload)
