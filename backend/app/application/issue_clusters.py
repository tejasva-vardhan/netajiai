"""Deterministic, privacy-preserving issue-cluster candidate policy.

This module does not decide that two complaints are duplicates. It derives a
stable candidate key from server-owned verified evidence and versioned policy
inputs so the persistence adapter can link reports without merging their
authoritative complaint records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import math
import re


@dataclass(frozen=True, slots=True)
class IssueClusterCandidate:
    cluster_key: str
    normalized_issue_type: str
    window_start: datetime
    supporter_ref_hash: str


@dataclass(frozen=True, slots=True)
class IssueClusterPolicy:
    """Versioned matching policy with no public location representation."""

    hmac_key: str
    policy_version: str = "issue-cluster.v1"
    cell_precision: int = 3
    window_hours: int = 72
    max_accuracy_m: float = 100.0

    def __post_init__(self) -> None:
        if len(self.hmac_key.encode("utf-8")) < 32:
            raise ValueError("Issue cluster HMAC key must be at least 32 bytes")
        if not self.policy_version.strip():
            raise ValueError("Issue cluster policy version is required")
        if not 1 <= self.cell_precision <= 6:
            raise ValueError("Issue cluster cell precision must be between 1 and 6")
        if self.window_hours < 1:
            raise ValueError("Issue cluster window must be positive")
        if self.max_accuracy_m <= 0:
            raise ValueError("Issue cluster maximum accuracy must be positive")

    def candidate(
        self,
        *,
        issue_type: str,
        latitude: float,
        longitude: float,
        accuracy_m: float,
        captured_at: datetime,
        supporter_ref: str,
    ) -> IssueClusterCandidate | None:
        """Return a candidate key only when server-owned evidence is precise enough.

        The cell and supporter identity are HMAC-derived and are never returned
        to an API caller. Fixed time buckets make the policy deterministic and
        bounded; human review may later decide whether a candidate is a true
        duplicate or collective issue.
        """

        if accuracy_m > self.max_accuracy_m:
            return None
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None
        normalized_issue_type = _normalize_issue_type(issue_type)
        if not normalized_issue_type:
            return None
        captured_at = _as_utc(captured_at)
        window_seconds = int(timedelta(hours=self.window_hours).total_seconds())
        epoch_seconds = int(captured_at.timestamp())
        window_start = datetime.fromtimestamp(
            epoch_seconds // window_seconds * window_seconds, tz=timezone.utc
        )
        scale = 10**self.cell_precision
        cell = f"{math.floor(latitude * scale)}:{math.floor(longitude * scale)}"
        material = "|".join(
            (
                self.policy_version,
                normalized_issue_type,
                cell,
                window_start.isoformat(),
            )
        )
        return IssueClusterCandidate(
            cluster_key=self._digest(material),
            normalized_issue_type=normalized_issue_type,
            window_start=window_start,
            supporter_ref_hash=self._digest(f"supporter|{supporter_ref}"),
        )

    def _digest(self, value: str) -> str:
        return hmac.new(
            self.hmac_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
        ).hexdigest()


def _normalize_issue_type(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
