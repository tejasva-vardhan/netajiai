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


class FailingDraftOrchestrator(FakeAgentOrchestrator):
    def extract_complaint(self, text, *, language=None, context=None):
        raise RuntimeError("draft provider unavailable")


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
    assert "DigiLocker" not in filing.json()["response_text"]
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


def test_conversation_uses_the_casual_handler_without_changing_workflow_action():
    engine = _engine()
    Base.metadata.create_all(engine)
    client = TestClient(_app(AuthenticatedPrincipal("oidc:casual"), engine))

    response = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "casual-turn-1"},
        json={"text": "hello", "language": "en"},
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "casual"
    assert response.json()["next_action"] == "continue_chat"
    assert "Namaste" in response.json()["response_text"]


def test_conversation_rejects_whitespace_only_turn_before_routing():
    engine = _engine()
    Base.metadata.create_all(engine)
    client = TestClient(_app(AuthenticatedPrincipal("oidc:blank-turn"), engine))

    response = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "blank-turn-1"},
        json={"text": "   \n\t", "language": "hi-IN"},
    )

    assert response.status_code == 422


def test_conversation_auto_transitions_between_general_filing_and_status_in_one_session():
    engine = _engine()
    Base.metadata.create_all(engine)
    client = TestClient(
        _app(AuthenticatedPrincipal("oidc:multi-workflow", identity_verified=True), engine)
    )

    casual = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "multi-casual"},
        json={"text": "Namaste", "language": "hi-IN"},
    )
    filing = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "multi-filing"},
        json={
            "text": "Meri complaint darj karni hai, gali mein pothole hai",
            "language": "hi-IN",
            "session_id": casual.json()["session_id"],
        },
    )
    status = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "multi-status"},
        json={
            "text": "Meri complaint ka status dekhna hai",
            "language": "hi-IN",
            "session_id": filing.json()["session_id"],
        },
    )

    assert casual.status_code == 200
    assert casual.json()["next_action"] == "continue_chat"
    assert filing.status_code == 200
    assert filing.json()["intent"] == "filing"
    assert filing.json()["next_action"] == "start_filing"
    assert status.status_code == 200
    assert status.json()["intent"] == "status"
    assert status.json()["next_action"] == "provide_receipt"
    assert status.json()["session_id"] == casual.json()["session_id"]


def test_conversation_continuation_rechecks_verification_before_resuming_filing():
    engine = _engine()
    Base.metadata.create_all(engine)
    state = {"verified": False}
    client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=sessionmaker(engine),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                "oidc:verification-transition", identity_verified=state["verified"]
            ),
            ai_orchestrator=FakeAgentOrchestrator(),
        )
    )

    filing = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "verification-transition-1"},
        json={"text": "Meri pothole complaint darj karni hai", "language": "hi-IN"},
    )
    state["verified"] = True
    resumed = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "verification-transition-2"},
        json={
            "text": "haan",
            "language": "hi-IN",
            "session_id": filing.json()["session_id"],
        },
    )

    assert filing.json()["next_action"] == "verify_identity"
    assert resumed.status_code == 200
    assert resumed.json()["next_action"] == "start_filing"


def test_conversation_continuation_rechecks_revoked_verification_before_filing():
    engine = _engine()
    Base.metadata.create_all(engine)
    state = {"verified": True}
    client = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=sessionmaker(engine),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                "oidc:verification-revoked", identity_verified=state["verified"]
            ),
            ai_orchestrator=FakeAgentOrchestrator(),
        )
    )

    filing = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "verification-revoked-1"},
        json={"text": "Meri pothole complaint darj karni hai", "language": "hi-IN"},
    )
    state["verified"] = False
    resumed = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "verification-revoked-2"},
        json={
            "text": "haan",
            "language": "hi-IN",
            "session_id": filing.json()["session_id"],
        },
    )

    assert filing.json()["next_action"] == "start_filing"
    assert resumed.status_code == 200
    assert resumed.json()["next_action"] == "verify_identity"


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
    assert response.json()["response_text"] == "Maine aapki baat samajh li. Ab complaint ko ek-ek karke complete karte hain."
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


def test_failed_turn_retry_cannot_replay_the_previous_turn_response():
    engine = _engine()
    Base.metadata.create_all(engine)
    client = TestClient(
        _app(
            AuthenticatedPrincipal("oidc:failed-turn", identity_verified=True),
            engine,
            FailingDraftOrchestrator(),
        )
    )

    first = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "failed-turn-first"},
        json={"text": "hello", "language": "en"},
    )
    failed = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "failed-turn-second"},
        json={
            "text": "Meri pothole complaint darj karni hai",
            "language": "hi-IN",
            "session_id": first.json()["session_id"],
        },
    )
    retry = client.post(
        "/api/v1/conversations/turn",
        headers={"Idempotency-Key": "failed-turn-second"},
        json={
            "text": "Meri pothole complaint darj karni hai",
            "language": "hi-IN",
            "session_id": first.json()["session_id"],
        },
    )

    assert first.status_code == 200
    assert failed.status_code == 503
    assert retry.status_code == 503
    assert retry.json()["detail"] == "Conversation service is temporarily unavailable"
    assert retry.json()["detail"] != first.json()["response_text"]

    with Session(engine) as session:
        record = session.get(SessionRecord, UUID(first.json()["session_id"]))
        assert record is not None
        assert record.state["last_intent"] == "casual"
        assert record.state["turn_count"] == 1
        assert record.state["last_response_turn_key_hash"]
        assert record.state["last_response"]["response_id"] == first.json()["response_id"]
