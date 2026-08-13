"""Bounded conversation router with one consistent response voice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.app.application.drafts import ComplaintDraftService, DraftRejected, DraftUnavailable
from backend.app.application.ports import AgentOrchestrator
from backend.app.application.schemes import SchemeKnowledgeService, SchemeKnowledgeUnavailable
from backend.app.application.tone_governor import (
    DeterministicToneGovernor,
    ToneGovernor,
    refusal_text,
)
from backend.app.contracts.ai import ComplaintDraftRequest, ComplaintExtraction, Intent
from backend.app.contracts.conversation import (
    ConversationContext,
    ConversationNextAction,
    ConversationTurnResponse,
)
from backend.app.contracts.identity import AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class ConversationSession:
    session_id: UUID
    citizen_id: str
    language: str | None
    last_intent: Intent | None
    turn_count: int
    last_turn_key_hash: str | None
    last_turn_fingerprint: str | None
    last_response: ConversationTurnResponse | None


class ConversationSessionRepository(Protocol):
    def get_owned(self, session_id: UUID, citizen_id: str) -> ConversationSession | None: ...

    def create_or_update(
        self,
        *,
        session_id: UUID,
        citizen_id: str,
        language: str | None,
        intent: Intent,
        turn_key_hash: str,
        turn_fingerprint: str,
        now: datetime,
    ) -> ConversationSession: ...

    def save_response(
        self,
        *,
        session_id: UUID,
        citizen_id: str,
        response: ConversationTurnResponse,
        now: datetime,
    ) -> None: ...


class ConversationUnavailable(RuntimeError):
    """The bounded router or durable session store is unavailable."""


class ConversationSessionOwnershipError(ValueError):
    """The supplied session does not belong to the authenticated citizen."""


class ConversationIdempotencyConflict(ValueError):
    """The same turn key was reused for different input."""


class ConversationService:
    """Route language to a narrow handler and render only approved facts."""

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        sessions: ConversationSessionRepository,
        drafts: ComplaintDraftService,
        schemes: SchemeKnowledgeService | None = None,
        tone_governor: ToneGovernor | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._sessions = sessions
        self._drafts = drafts
        self._schemes = schemes
        self._tone_governor = tone_governor or DeterministicToneGovernor()

    def turn(
        self,
        principal: AuthenticatedPrincipal,
        *,
        text: str,
        language: str | None,
        session_id: UUID | None,
        idempotency_key: str,
        now: datetime,
    ) -> ConversationTurnResponse:
        if not principal.subject_ref.strip():
            raise ConversationUnavailable("Authenticated identity is required")
        if not idempotency_key.strip():
            raise ConversationIdempotencyConflict("Idempotency-Key is required")
        turn_key_hash = _sha256(idempotency_key)
        turn_fingerprint = _fingerprint(text, language)
        effective_session_id = session_id or uuid5(
            NAMESPACE_URL,
            f"aineta-session:{principal.subject_ref}:{idempotency_key}",
        )
        try:
            existing_session = self._sessions.get_owned(
                effective_session_id, principal.subject_ref
            )
            if session_id is not None and existing_session is None:
                raise ConversationSessionOwnershipError("Conversation session was not found")
            if (
                existing_session is not None
                and existing_session.last_turn_key_hash == turn_key_hash
                and existing_session.last_turn_fingerprint != turn_fingerprint
            ):
                raise ConversationIdempotencyConflict(
                    "Conversation idempotency key belongs to another request"
                )
            if (
                existing_session is not None
                and existing_session.last_turn_key_hash == turn_key_hash
                and existing_session.last_response is not None
            ):
                return existing_session.last_response
            context = _context_for_session(
                effective_session_id, language, existing_session
            )
            classification = self._orchestrator.classify_intent(
                text.strip(), context=context
            )
            current_session = self._sessions.create_or_update(
                session_id=effective_session_id,
                citizen_id=principal.subject_ref,
                language=language,
                intent=classification.intent,
                turn_key_hash=turn_key_hash,
                turn_fingerprint=turn_fingerprint,
                now=now,
            )
        except (ConversationSessionOwnershipError, ConversationIdempotencyConflict):
            raise
        except Exception as exc:
            raise ConversationUnavailable("Conversation service is temporarily unavailable") from exc

        draft: ComplaintExtraction | None = None
        next_action: ConversationNextAction
        response_text: str
        scheme_sources = []
        tone_decision = self._tone_governor.review(text)
        if (
            classification.intent in {"casual", "continuation"}
            and not tone_decision.allowed
        ):
            if tone_decision.category is None:  # pragma: no cover - policy invariant
                raise ConversationUnavailable("Conversation safety policy is incomplete")
            response_text = refusal_text(tone_decision.category)
            next_action = "safety_refusal"
        elif classification.intent == "filing":
            if not principal.identity_verified:
                response_text = "Shikayat darj karne se pehle DigiLocker se pehchaan verify karein."
                next_action = "verify_identity"
            else:
                try:
                    draft = self._drafts.extract(
                        principal,
                        ComplaintDraftRequest(text=text, language=language),
                        context=context,
                    )
                except (DraftRejected, DraftUnavailable) as exc:
                    raise ConversationUnavailable(
                        "Complaint drafting is temporarily unavailable"
                    ) from exc
                if draft.issue_type and not draft.missing_fields:
                    response_text = "Maine aapki baat samjhi hai. Photo, location aur voice note ke saath ise pakka karein."
                    next_action = "start_filing"
                else:
                    response_text = "Issue ko thoda aur saaf batayein—jaise sadak, paani, kachra ya streetlight."
                    next_action = "start_filing"
        elif classification.intent == "status":
            response_text = "Receipt token bhejkar shikayat ka status dekhein. Main bina verified receipt ke status nahi bataunga."
            next_action = "provide_receipt"
        elif classification.intent == "scheme":
            if self._schemes is None:
                response_text = "Is yojana ke liye verified information abhi available nahi hai. Main eligibility ka anuman nahi lagaunga."
                next_action = "scheme_unavailable"
            else:
                try:
                    scheme_answer = self._schemes.answer(
                        query=text,
                        language=language,
                        jurisdiction_code=None,
                        now=now,
                    )
                except SchemeKnowledgeUnavailable as exc:
                    raise ConversationUnavailable(str(exc)) from exc
                response_text = scheme_answer.answer_text
                scheme_sources = scheme_answer.sources
                next_action = (
                    "scheme_answer"
                    if scheme_answer.status == "answered"
                    else "scheme_unavailable"
                )
        elif classification.intent == "continuation":
            if context.last_next_action == "verify_identity":
                response_text = "Shikayat darj karne se pehle DigiLocker se pehchaan verify karein."
                next_action = "verify_identity"
            elif context.last_next_action == "start_filing":
                response_text = "Photo, location aur voice note ke saath shikayat pakki karein."
                next_action = "start_filing"
            elif context.last_next_action == "provide_receipt":
                response_text = "Receipt token bhejkar shikayat ka status dekhein."
                next_action = "provide_receipt"
            else:
                response_text = "Main civic problem samajhne, shikayat darj karne aur uska status dikhane mein madad kar sakta hoon."
                next_action = "continue_chat"
        else:
            response_text = "Main civic problem samajhne, shikayat darj karne aur uska status dikhane mein madad kar sakta hoon."
            next_action = "continue_chat"

        response = ConversationTurnResponse(
            session_id=current_session.session_id,
            response_id=uuid5(
                NAMESPACE_URL,
                f"aineta-response:{current_session.session_id}:{idempotency_key}",
            ),
            intent=classification.intent,
            confidence=classification.confidence,
            response_text=response_text,
            next_action=next_action,
            # The filing screen receives the citizen's draft through its own
            # verified draft boundary. Keep this conversational snapshot
            # structured but never persist raw pre-submission complaint text.
            complaint_draft=(
                draft.model_copy(update={"description": None})
                if draft is not None
                else None
            ),
            scheme_sources=scheme_sources,
        )
        try:
            self._sessions.save_response(
                session_id=current_session.session_id,
                citizen_id=principal.subject_ref,
                response=response,
                now=now,
            )
        except Exception as exc:
            raise ConversationUnavailable(
                "Conversation response could not be persisted"
            ) from exc
        return response


def _context_for_session(
    session_id: UUID,
    language: str | None,
    session: ConversationSession | None,
) -> ConversationContext:
    if session is None:
        return ConversationContext(session_id=session_id, language=language, turn_count=0)
    response = session.last_response
    return ConversationContext(
        session_id=session.session_id,
        language=language or session.language,
        last_intent=session.last_intent,
        last_next_action=response.next_action if response else None,
        turn_count=session.turn_count,
        previous_response_id=response.response_id if response else None,
        complaint_draft=response.complaint_draft if response else None,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(text: str, language: str | None) -> str:
    return _sha256(
        json.dumps(
            {"text": text.strip(), "language": language},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
