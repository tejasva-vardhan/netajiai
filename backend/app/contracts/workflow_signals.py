"""API contracts for structured complaint-workflow signals."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator



ClosureProofType = Literal[
    "after_media",
    "work_order",
    "department_reference",
    "human_review",
]
ReplyClassification = Literal["substantive", "weak", "duplicate", "unavailable"]
CitizenResolutionOutcome = Literal[
    "fully_solved",
    "partially_solved",
    "not_solved",
]


class ClosureProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proof_type: ClosureProofType
    proof_reference: str = Field(min_length=1, max_length=512)


class DepartmentResponseSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["fix_reported", "no_resolution"]
    proof: ClosureProofRequest | None = None
    reply_text: str | None = Field(default=None, min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_proof_for_outcome(self) -> "DepartmentResponseSignalRequest":
        if self.outcome == "fix_reported" and self.proof is None:
            raise ValueError("A fix report requires closure proof")
        if self.outcome == "no_resolution" and self.proof is not None:
            raise ValueError("Closure proof is only valid for a fix report")
        return self


class CitizenConfirmationSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: CitizenResolutionOutcome


class RoutingActivationSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowSignalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complaint_id: UUID
    signal_id: UUID
    accepted: bool
    reply_id: UUID | None = None
    reply_classification: ReplyClassification | None = None
