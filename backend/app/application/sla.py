"""Versioned SLA policy ports and the explicit synthetic fixture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SlaSnapshot:
    """The immutable timing policy captured when a complaint is accepted."""

    policy_version: str
    response_timeout_seconds: int
    post_escalation_timeout_seconds: int

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("SLA policy version is required")
        if self.response_timeout_seconds < 1:
            raise ValueError("SLA response timeout must be positive")
        if self.post_escalation_timeout_seconds < 1:
            raise ValueError("SLA post-escalation timeout must be positive")


class SlaPolicy(Protocol):
    def resolve(self, issue_type: str) -> SlaSnapshot: ...


class SlaPolicyUnavailable(RuntimeError):
    """No approved SLA policy could safely be resolved."""


class SyntheticSlaPolicy:
    """Controlled fixture for development and synthetic MP demonstrations."""

    policy_version = "synthetic-sla.v1"
    _POST_ESCALATION_TIMEOUT_SECONDS = 30 * 24 * 60 * 60
    _RESPONSE_TIMEOUTS = {
        "water": 48 * 60 * 60,
        "electricity": 48 * 60 * 60,
        "garbage": 48 * 60 * 60,
        "sanitation": 48 * 60 * 60,
        "streetlight": 72 * 60 * 60,
        "road": 5 * 24 * 60 * 60,
    }

    def resolve(self, issue_type: str) -> SlaSnapshot:
        normalized = issue_type.strip().casefold()
        if not normalized:
            raise SlaPolicyUnavailable("Issue type is required for SLA resolution")
        return SlaSnapshot(
            policy_version=self.policy_version,
            response_timeout_seconds=self._RESPONSE_TIMEOUTS.get(
                normalized, 72 * 60 * 60
            ),
            post_escalation_timeout_seconds=self._POST_ESCALATION_TIMEOUT_SECONDS,
        )
