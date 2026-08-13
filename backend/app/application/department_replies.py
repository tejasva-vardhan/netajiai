"""Private department-reply records and bounded response classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Protocol
from uuid import UUID

from backend.app.contracts.workflow_signals import ReplyClassification


@dataclass(frozen=True, slots=True)
class DepartmentReply:
    reply_id: UUID
    complaint_id: UUID
    classification: ReplyClassification
    classification_reason: str
    response_text_hash: str | None
    request_fingerprint: str


class DepartmentReplyRepository(Protocol):
    def find_by_idempotency_key(
        self, complaint_id: UUID, idempotency_key: str
    ) -> DepartmentReply | None: ...

    def has_text_hash(self, complaint_id: UUID, response_text_hash: str) -> bool: ...

    def reserve(
        self,
        *,
        reply_id: UUID,
        complaint_id: UUID,
        submitted_by: str,
        outcome: str,
        response_text: str | None,
        response_text_hash: str | None,
        classification: ReplyClassification,
        classification_reason: str,
        classification_policy_version: str,
        proof_claim_id: UUID | None,
        idempotency_key: str,
        request_fingerprint: str,
        received_at: datetime,
    ) -> DepartmentReply: ...


class DepartmentReplyConflict(ValueError):
    """The reply idempotency key was reused for different content."""


class WeakReplyClassifier(Protocol):
    policy_version: str

    def classify(
        self, response_text: str | None, *, duplicate: bool
    ) -> tuple[ReplyClassification, str]: ...


class DeterministicWeakReplyClassifier:
    """Conservative signal classifier; it cannot mutate complaint state."""

    policy_version = "weak-reply.v1"
    _weak_patterns: tuple[str, ...] = (
        r"\bunder process\b",
        r"\bin progress\b",
        r"\bbeing processed\b",
        r"\bwill look into\b",
        r"\baction will be taken\b",
        r"\bsoon\b",
        r"\bforwarded\b",
        r"\bnoted\b",
        "प्रक्रिया में",
        "विचाराधीन",
        "जल्द",
        "देख रहे हैं",
        "कार्रवाई की जाएगी",
    )
    _substantive_patterns: tuple[str, ...] = (
        r"\bcompleted\b",
        r"\bresolved\b",
        r"\brepaired\b",
        r"\bwork order\b",
        r"\bclosed\b",
        "काम पूरा",
        "समस्या हल",
        "मरम्मत हो गई",
    )

    def classify(
        self, response_text: str | None, *, duplicate: bool
    ) -> tuple[ReplyClassification, str]:
        normalized = _normalize(response_text)
        if not normalized:
            return "unavailable", "no_reply_text"
        if duplicate:
            return "duplicate", "same_reply_hash_for_complaint"
        if any(re.search(pattern, normalized) for pattern in self._weak_patterns):
            return "weak", "non_substantive_status_language"
        if any(re.search(pattern, normalized) for pattern in self._substantive_patterns):
            return "substantive", "resolution_language_present"
        return "substantive", "unclassified_department_response"


def normalize_reply_text(value: str | None) -> str | None:
    normalized = _normalize(value)
    return normalized or None


def reply_text_hash(value: str | None) -> str | None:
    normalized = normalize_reply_text(value)
    if normalized is None:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())
