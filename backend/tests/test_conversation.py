from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from uuid import UUID

from backend.app.ai.fakes import FakeAgentOrchestrator
from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.contracts.identity import IdentityVerificationResult
from backend.app.contracts.conversation import ConversationContext
from backend.app.infrastructure.db import Base, SessionRecord
from backend.app.infrastructure.identity_repositories import SqlAlchemyIdentityVerificationRepository


class CountingFakeAgentOrchestrator(FakeAgentOrchestrator):
    def __init__(self):
        self.classification_calls = 0

    def classify_intent(self, text, *, context: ConversationContext | None = None):
        self.classification_calls += 1
        return super().classify_intent(text, context=context)


def _app(principal: AuthenticatedPrincipal, engine, orchestrator=None):
    return create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: principal,
        ai_orchestrator=orchestrator or FakeAgentOrchestrator(),
    )


def _engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_conversation_router_persists_structured_context_and_keeps_scheme_answers_grounded():
    engine = _engine()
    Base.metadata.create_all(engine)
    client = TestClient(
        _app(AuthenticatedPrincipal("oidc:citizen-1"), engine)
    )

    filing = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "turn-1"},
        json={"text": "Gali mein pothole hai", "language": "hi-IN"},
    )
    scheme = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "turn-2"},
        json={"text": "Is yojana ke liye meri eligibility kya hai?", "language": "hi-IN"},
    )
    safety = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "turn-safety-1"},
        json={"text": "Which political party should I vote for?", "language": "en"},
    )
    retry = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "turn-1"},
        json={"text": "Gali mein pothole hai", "language": "hi-IN"},
    )
    conflict = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "turn-1"},
        json={"text": "Gali mein paani hai", "language": "hi-IN"},
    )

    assert filing.status_code == 200
    assert filing.json()["intent"] == "filing"
    assert filing.json()["next_action"] == "verify_identity"
    assert filing.json()["complaint_draft"] is None
    assert scheme.status_code == 200
    assert scheme.json()["next_action"] == "scheme_unavailable"
    assert "verified information" in scheme.json()["response_text"]
    assert safety.status_code == 200
    assert safety.json()["next_action"] == "safety_refusal"
    assert "political" not in safety.json()["response_text"].casefold()
    assert retry.status_code == 200
    assert retry.json()["response_id"] == filing.json()["response_id"]
    assert conflict.status_code == 409

    with Session(engine) as session:
        record = session.get(SessionRecord, UUID(filing.json()["session_id"]))
        assert record is not None
        assert record.state["last_intent"] == "filing"
        assert record.state["turn_count"] == 1
        assert "pothole" not in str(record.state)

    continuation = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "turn-continue-1"},
        json={
            "text": "haan",
            "language": "hi-IN",
            "session_id": filing.json()["session_id"],
        },
    )
    assert continuation.status_code == 200
    assert continuation.json()["intent"] == "continuation"
    assert continuation.json()["next_action"] == "verify_identity"

    with Session(engine) as session:
        record = session.get(SessionRecord, UUID(filing.json()["session_id"]))
        assert record is not None
        assert record.state["last_intent"] == "continuation"
        assert record.state["turn_count"] == 2
        assert record.state["last_response"]["next_action"] == "verify_identity"
        assert "pothole" not in str(record.state)


def test_verified_filing_returns_structured_draft_and_session_is_citizen_scoped():
    engine = _engine()
    Base.metadata.create_all(engine)
    client = TestClient(
        _app(AuthenticatedPrincipal("oidc:citizen-2", identity_verified=True), engine)
    )

    response = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "turn-verified-1"},
        json={"text": "There is a large pothole", "language": "en"},
    )
    assert response.status_code == 200
    assert response.json()["next_action"] == "start_filing"
    assert response.json()["complaint_draft"]["issue_type"] == "road"
    assert response.json()["complaint_draft"]["description"] is None

    with Session(engine) as session:
        record = session.get(SessionRecord, UUID(response.json()["session_id"]))
        assert record is not None
        assert "large pothole" not in str(record.state)

    other_client = TestClient(
        _app(AuthenticatedPrincipal("oidc:other"), engine)
    )
    reused = other_client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "other-turn-1"},
        json={
            "text": "continue",
            "session_id": response.json()["session_id"],
        },
    )
    assert reused.status_code == 404


def test_conversation_uses_persisted_digilocker_verification_for_filing_handoff():
    engine = _engine()
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)
    with Session(engine) as session:
        SqlAlchemyIdentityVerificationRepository(session).save(
            IdentityVerificationResult(
                subject_ref="oidc:citizen-chat-verified",
                status="verified",
                provider="digilocker",
                method="requester_oauth",
                consent_id="chat-consent",
                verified_at=now,
            ),
            reference_hash="c" * 64,
            retention_until=None,
            now=now,
        )

    client = TestClient(
        _app(AuthenticatedPrincipal("oidc:citizen-chat-verified"), engine)
    )
    response = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "chat-verified-turn"},
        json={"text": "Gali mein pothole hai", "language": "hi-IN"},
    )

    assert response.status_code == 200
    assert response.json()["next_action"] == "start_filing"
    assert response.json()["complaint_draft"]["issue_type"] == "road"


def test_conversation_retry_replays_persisted_response_without_reclassifying():
    engine = _engine()
    Base.metadata.create_all(engine)
    orchestrator = CountingFakeAgentOrchestrator()
    client = TestClient(
        _app(AuthenticatedPrincipal("oidc:citizen-retry"), engine, orchestrator)
    )
    payload = {"text": "Gali mein pothole hai", "language": "hi-IN"}

    first = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "retryable-turn"},
        json=payload,
    )
    retry = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "retryable-turn"},
        json=payload,
    )

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert orchestrator.classification_calls == 1
