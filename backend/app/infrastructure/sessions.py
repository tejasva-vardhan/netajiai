"""Durable session context; raw turns stay out of storage.

The latest bounded response is retained only to replay a completed
idempotent turn without another model/provider call.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.conversation import ConversationSession
from backend.app.contracts.ai import Intent
from backend.app.contracts.conversation import ConversationTurnResponse
from backend.app.infrastructure.db import SessionRecord


class SqlAlchemyConversationSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_owned(self, session_id: UUID, citizen_id: str) -> ConversationSession | None:
        record = self._session.scalar(
            select(SessionRecord).where(
                SessionRecord.id == session_id,
                SessionRecord.citizen_id == citizen_id,
            )
        )
        return self._view(record) if record is not None else None

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
    ) -> ConversationSession:
        record = self._session.scalar(
            select(SessionRecord).where(
                SessionRecord.id == session_id,
                SessionRecord.citizen_id == citizen_id,
            )
        )
        if record is None:
            record = SessionRecord(
                id=session_id,
                citizen_id=citizen_id,
                channel="api",
                language=language,
                state={
                    "last_intent": intent,
                    "turn_count": 1,
                    "last_turn_key_hash": turn_key_hash,
                    "last_turn_fingerprint": turn_fingerprint,
                },
                created_at=now,
                updated_at=now,
            )
            self._session.add(record)
        else:
            state = dict(record.state)
            same_turn = state.get("last_turn_key_hash") == turn_key_hash
            state["last_intent"] = intent
            state["turn_count"] = int(state.get("turn_count", 0)) + (0 if same_turn else 1)
            state["last_turn_key_hash"] = turn_key_hash
            state["last_turn_fingerprint"] = turn_fingerprint
            record.state = state
            record.language = language or record.language
            record.updated_at = now
        self._session.commit()
        self._session.refresh(record)
        return self._view(record)

    def save_response(
        self,
        *,
        session_id: UUID,
        citizen_id: str,
        response: ConversationTurnResponse,
        now: datetime,
    ) -> None:
        record = self._session.scalar(
            select(SessionRecord).where(
                SessionRecord.id == session_id,
                SessionRecord.citizen_id == citizen_id,
            )
        )
        if record is None:
            raise ValueError("Conversation session was not found")
        state = dict(record.state)
        state["last_response"] = _without_draft_text(response).model_dump(mode="json")
        record.state = state
        record.updated_at = now
        self._session.commit()

    @staticmethod
    def _view(record: SessionRecord) -> ConversationSession:
        response = record.state.get("last_response")
        last_response = _without_draft_text(ConversationTurnResponse.model_validate(response)) if isinstance(response, dict) else None
        return ConversationSession(
            session_id=record.id,
            citizen_id=record.citizen_id,
            language=record.language,
            last_intent=record.state.get("last_intent"),
            turn_count=int(record.state.get("turn_count", 0)),
            last_turn_key_hash=record.state.get("last_turn_key_hash"),
            last_turn_fingerprint=record.state.get("last_turn_fingerprint"),
            last_response=last_response,
        )


def _without_draft_text(response: ConversationTurnResponse) -> ConversationTurnResponse:
    if response.complaint_draft is None:
        return response
    return response.model_copy(
        update={
            "complaint_draft": response.complaint_draft.model_copy(
                update={"description": None}
            )
        }
    )
