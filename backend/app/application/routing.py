"""Server-owned routing decisions for the complaint creation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RoutingState = Literal["active", "mapping_in_progress"]


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """A policy result, never a model-generated instruction."""

    state: RoutingState
    jurisdiction_code: str | None = None
    snapshot_ref: str | None = None
    reason_code: str = "mapping_unavailable"

    @classmethod
    def mapping_in_progress(cls, *, reason_code: str = "mapping_unavailable") -> "RoutingDecision":
        return cls(state="mapping_in_progress", reason_code=reason_code)


class RoutingResolverUnavailable(RuntimeError):
    """Raised when routing cannot be safely evaluated."""
