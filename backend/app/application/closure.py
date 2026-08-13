"""Provider-neutral proof boundary for department-reported resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from backend.app.contracts.workflow_signals import ClosureProofType


@dataclass(frozen=True, slots=True)
class ClosureProofVerification:
    accepted: bool
    verifier: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ClosureProofClaim:
    claim_id: UUID
    complaint_id: UUID
    proof_type: ClosureProofType
    proof_reference_hash: str
    submitted_by: str
    status: Literal["accepted", "rejected"]
    verifier: str
    request_fingerprint: str
    verified_at: datetime | None
    created_at: datetime


class ClosureProofVerifier(Protocol):
    """Verify an opaque proof reference without deciding lifecycle state."""

    def verify(
        self,
        *,
        complaint_id: UUID,
        proof_type: ClosureProofType,
        proof_reference: str,
        submitted_by: str,
        now: datetime,
    ) -> ClosureProofVerification: ...


class ClosureProofRepository(Protocol):
    """Persist and retrieve accepted proof claims without raw references."""

    def find_by_idempotency_key(
        self, complaint_id: UUID, idempotency_key: str
    ) -> ClosureProofClaim | None: ...

    def find_for_complaint(
        self, complaint_id: UUID, claim_id: UUID
    ) -> ClosureProofClaim | None: ...

    def find_by_reference_hash(
        self, complaint_id: UUID, proof_reference_hash: str
    ) -> ClosureProofClaim | None: ...

    def reserve(
        self,
        *,
        claim_id: UUID,
        complaint_id: UUID,
        proof_type: ClosureProofType,
        proof_reference_hash: str,
        submitted_by: str,
        verifier: str,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> ClosureProofClaim: ...


class ClosureProofRequired(ValueError):
    """A fix report cannot proceed without an explicit proof claim."""


class ClosureProofRejected(ValueError):
    """The supplied proof was not accepted by the configured verifier."""


class ClosureProofUnavailable(RuntimeError):
    """No production proof verifier is available."""


class ClosureProofConflict(ValueError):
    """A proof idempotency key was reused for another proof payload."""
