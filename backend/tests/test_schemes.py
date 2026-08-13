from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.main import create_app
from backend.app.application.schemes import SchemeKnowledgeService
from backend.app.application.schemes import SchemeReviewRejected, SchemeReviewService
from backend.app.config import Settings
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.contracts.schemes import SchemeIngestionRequest
from backend.app.infrastructure.db import Base, SchemeRecord, SchemeSourceRecord
from backend.app.infrastructure.schemes import SqlAlchemySchemeKnowledgeRepository


def _engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _approved_scheme(session: Session, *, source_status: str = "approved") -> None:
    now = datetime.now(timezone.utc)
    scheme = SchemeRecord(
        id=uuid4(),
        scheme_key="synthetic-water-support",
        language="hi-IN",
        jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
        title="Synthetic Water Support",
        answer_text="Verified answer: apply through the listed local office.",
        eligibility_summary={"reviewed": True},
        search_terms="water paani support sahayata",
        review_status="approved",
        version="1",
        reviewed_at=now,
        created_at=now,
        updated_at=now,
    )
    scheme.sources = [
        SchemeSourceRecord(
            id=uuid4(),
            title="Synthetic source",
            publisher="Controlled fixture",
            url="https://example.test/synthetic-water-support",
            document_hash="a" * 64,
            retrieved_at=now,
            review_status=source_status,
            reviewed_at=now if source_status == "approved" else None,
            created_at=now,
        )
    ]
    session.add(scheme)
    session.commit()


def test_scheme_answers_require_approved_current_source_and_cite_it():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _approved_scheme(session)
        answer = SchemeKnowledgeService(SqlAlchemySchemeKnowledgeRepository(session)).answer(
            query="paani support",
            language="hi-IN",
            jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
            now=datetime.now(timezone.utc),
        )

    assert answer.status == "answered"
    assert answer.answer_text.startswith("Verified answer")
    assert len(answer.sources) == 1
    assert answer.sources[0].url.endswith("synthetic-water-support")


def test_scheme_falls_back_when_no_reviewed_source_matches():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _approved_scheme(session, source_status="pending")
        answer = SchemeKnowledgeService(SqlAlchemySchemeKnowledgeRepository(session)).answer(
            query="paani support",
            language="hi-IN",
            jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
            now=datetime.now(timezone.utc),
        )

    assert answer.status == "unavailable"
    assert answer.sources == []


def test_scheme_endpoint_exposes_grounded_answer_or_safe_fallback():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _approved_scheme(session)
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda _: AuthenticatedPrincipal("citizen:1"),
    )

    response = TestClient(app).post(
        "/api/v1/schemes/answer",
        json={
            "query": "paani support",
            "language": "hi-IN",
            "jurisdiction_code": "IN-MP-SYNTHETIC-BHOPAL",
        },
    )
    missing = TestClient(app).post(
        "/api/v1/schemes/answer",
        json={"query": "unknown scheme", "language": "hi-IN"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["sources"][0]["url"].startswith("https://")
    assert missing.status_code == 200
    assert missing.json()["status"] == "unavailable"


def test_scheme_ingestion_stays_unavailable_until_explicit_reviewer_approval():
    engine = _engine()
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    payload = SchemeIngestionRequest(
        scheme_key="synthetic-reviewed-support",
        language="hi-IN",
        jurisdiction_code="IN-MP-SYNTHETIC-BHOPAL",
        title="Synthetic Reviewed Support",
        answer_text="Apply using the reviewed source.",
        eligibility_summary={"reviewed": True},
        search_terms="support sahayata",
        version="1",
        sources=[
            {
                "title": "Controlled authority source",
                "publisher": "Controlled fixture",
                "url": "https://example.test/synthetic-reviewed-support",
                "document_hash": "f" * 64,
                "retrieved_at": now,
            }
        ],
    )

    with Session(engine) as session:
        repository = SqlAlchemySchemeKnowledgeRepository(session)
        review = SchemeReviewService(repository)
        scheme_id = review.stage(payload, now=now)
        assert review.stage(payload, now=now) == scheme_id
        unavailable = SchemeKnowledgeService(repository).answer(
            query="support", language="hi-IN", jurisdiction_code=None, now=now
        )
        assert unavailable.status == "unavailable"

        approval = review.approve(scheme_id, reviewer_id="moderator:1", now=now)
        assert approval.status == "approved"
        answered = SchemeKnowledgeService(repository).answer(
            query="support", language="hi-IN", jurisdiction_code=None, now=now
        )
        assert answered.status == "answered"
        assert answered.sources[0].url.startswith("https://")


def test_scheme_ingestion_rejects_non_https_sources():
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    payload = SchemeIngestionRequest(
        scheme_key="synthetic-invalid-source",
        language="en-IN",
        title="Invalid source",
        answer_text="Not public.",
        search_terms="invalid",
        version="1",
        sources=[
            {
                "title": "Unsafe source",
                "publisher": "Fixture",
                "url": "http://example.test/unsafe",
                "document_hash": "1" * 64,
                "retrieved_at": now,
            }
        ],
    )

    with Session(_engine()) as session:
        service = SchemeReviewService(SqlAlchemySchemeKnowledgeRepository(session))
        with pytest.raises(SchemeReviewRejected, match="HTTPS"):
            service.stage(payload, now=now)


def test_scheme_review_queue_returns_bounded_pending_content_with_cursor():
    engine = _engine()
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

    def payload(key: str, version: str) -> SchemeIngestionRequest:
        return SchemeIngestionRequest(
            scheme_key=key,
            language="hi-IN",
            title=f"{key} title",
            answer_text="Only the reviewed answer may be shown to citizens.",
            search_terms="support sahayata",
            version=version,
            sources=[
                {
                    "title": "Authority source",
                    "publisher": "Controlled fixture",
                    "url": f"https://example.test/{key}",
                    "document_hash": ("a" if version == "1" else "b") * 64,
                    "retrieved_at": now,
                }
            ],
        )

    with Session(engine) as session:
        review = SchemeReviewService(SqlAlchemySchemeKnowledgeRepository(session))
        review.stage(payload("pending-first", "1"), now=now)
        review.stage(payload("pending-second", "1"), now=now)

        first = review.list_pending(limit=1, cursor=None)
        second = review.list_pending(limit=1, cursor=first.next_cursor)

    assert len(first.items) == 1
    assert first.next_cursor
    assert first.items[0].review_status == "pending_review"
    assert first.items[0].sources[0].url.startswith("https://")
    assert len(second.items) == 1
    assert second.items[0].scheme_id != first.items[0].scheme_id


def test_scheme_review_http_endpoints_require_operator_and_content_reviewer_roles():
    engine = _engine()
    Base.metadata.create_all(engine)

    def principal_for_token(authorization: str) -> AuthenticatedPrincipal:
        if authorization.endswith("operator"):
            return AuthenticatedPrincipal("operator:1", roles=frozenset({"operator"}))
        return AuthenticatedPrincipal("moderator:1", roles=frozenset({"moderator"}))

    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=principal_for_token,
    )
    client = TestClient(app)
    body = {
        "scheme_key": "synthetic-http-review",
        "language": "hi-IN",
        "title": "HTTP review fixture",
        "answer_text": "Use the approved source.",
        "search_terms": "review fixture",
        "version": "1",
        "sources": [
            {
                "title": "HTTP source",
                "publisher": "Controlled fixture",
                "url": "https://example.test/http-review",
                "document_hash": "2" * 64,
                "retrieved_at": "2026-08-05T12:00:00Z",
            }
        ],
    }

    staged = client.post(
        "/api/v1/admin/schemes",
        headers={"Authorization": "Bearer operator"},
        json=body,
    )
    assert staged.status_code == 201
    scheme_id = staged.json()["scheme_id"]

    forbidden = client.post(
        f"/api/v1/admin/schemes/{scheme_id}/approve",
        headers={"Authorization": "Bearer operator"},
    )
    assert forbidden.status_code == 403

    approved = client.post(
        f"/api/v1/admin/schemes/{scheme_id}/approve",
        headers={"Authorization": "Bearer moderator"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] == "moderator:1"


def test_scheme_review_queue_is_reviewer_only():
    engine = _engine()
    Base.metadata.create_all(engine)
    app = create_app(
        Settings(environment="test"),
        session_factory=sessionmaker(engine),
        principal_resolver=lambda authorization: AuthenticatedPrincipal(
            "operator:1",
            roles=frozenset({"operator"})
            if authorization.endswith("operator")
            else frozenset({"moderator"}),
        ),
    )
    client = TestClient(app)

    operator = client.get(
        "/api/v1/admin/schemes/review-queue",
        headers={"Authorization": "Bearer operator"},
    )
    moderator = client.get(
        "/api/v1/admin/schemes/review-queue",
        headers={"Authorization": "Bearer moderator"},
    )

    assert operator.status_code == 403
    assert moderator.status_code == 200
    assert moderator.json() == {"items": [], "next_cursor": None}
