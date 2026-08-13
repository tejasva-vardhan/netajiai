"""Application boundary for non-authoritative complaint drafting."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.application.ports import AgentOrchestrator
from backend.app.contracts.ai import ComplaintDraftRequest, ComplaintExtraction
from backend.app.contracts.conversation import ConversationContext
from backend.app.contracts.identity import AuthenticatedPrincipal


class DraftRejected(ValueError):
    """Raised when an unverified principal requests a complaint draft."""


class DraftUnavailable(RuntimeError):
    """Raised when no bounded language adapter is configured."""


@dataclass(frozen=True, slots=True)
class ComplaintDraftService:
    """Run extraction only; this service cannot create or mutate a complaint."""

    orchestrator: AgentOrchestrator

    def extract(
        self,
        principal: AuthenticatedPrincipal,
        request: ComplaintDraftRequest,
        *,
        context: ConversationContext | None = None,
    ) -> ComplaintExtraction:
        if not principal.subject_ref.strip() or not principal.identity_verified:
            raise DraftRejected("Verified citizen identity is required")
        try:
            extraction = self.orchestrator.extract_complaint(
                request.text.strip(), language=request.language, context=context
            )
        except Exception as exc:
            raise DraftUnavailable("Complaint extraction is temporarily unavailable") from exc
        return ComplaintExtraction.model_validate(extraction)
