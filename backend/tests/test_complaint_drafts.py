from fastapi.testclient import TestClient

from backend.app.ai.fakes import FakeAgentOrchestrator
from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.contracts.identity import AuthenticatedPrincipal


class FailingAgentOrchestrator(FakeAgentOrchestrator):
    def extract_complaint(self, text, *, language=None, context=None):
        raise RuntimeError("provider secret must not reach the client")


def test_draft_endpoint_returns_structured_extraction_without_creating_state():
    client = TestClient(
        create_app(
            Settings(environment="test"),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                "digilocker:citizen-1", identity_verified=True
            ),
            ai_orchestrator=FakeAgentOrchestrator(),
        )
    )

    response = client.post(
        "/api/v1/complaints/draft",
        headers={"Authorization": "Bearer test-token"},
        json={"text": "Gali mein bada pothole hai", "language": "hi-IN"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "issue_type": "road",
        "description": "Gali mein bada pothole hai",
        "language": "hi-IN",
        "missing_fields": [],
        "confidence": 0.8,
    }


def test_draft_endpoint_fails_closed_without_ai_adapter():
    client = TestClient(
        create_app(
            Settings(environment="test"),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                "digilocker:citizen-2", identity_verified=True
            ),
        )
    )

    response = client.post(
        "/api/v1/complaints/draft",
        headers={"Authorization": "Bearer test-token"},
        json={"text": "There is standing water", "language": "en"},
    )

    assert response.status_code == 503


def test_draft_endpoint_sanitizes_provider_failures():
    client = TestClient(
        create_app(
            Settings(environment="test"),
            principal_resolver=lambda _: AuthenticatedPrincipal(
                "digilocker:citizen-3", identity_verified=True
            ),
            ai_orchestrator=FailingAgentOrchestrator(),
        )
    )

    response = client.post(
        "/api/v1/complaints/draft",
        headers={"Authorization": "Bearer test-token"},
        json={"text": "There is standing water", "language": "en"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Complaint drafting is temporarily unavailable"
    }
    assert "provider secret" not in response.text
