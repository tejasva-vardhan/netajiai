from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.main import create_app
from backend.app.config import Settings


def test_health_exposes_service_contract_without_provider_calls():
    client = TestClient(create_app(Settings(environment="test", service_name="test-api")))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "test-api",
        "environment": "test",
        "version": "0.1.0",
    }


def test_readiness_requires_a_database_and_returns_bounded_checks():
    unconfigured = TestClient(create_app(Settings(environment="test")))
    assert unconfigured.get("/ready").status_code == 503

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    configured = TestClient(
        create_app(
            Settings(environment="test"),
            session_factory=lambda: Session(engine),
        )
    )
    response = configured.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {"database": "ok"}


def test_http_correlation_id_is_returned_and_untrusted_values_are_replaced():
    client = TestClient(create_app(Settings(environment="test")))

    supplied = client.get("/health", headers={"X-Request-ID": "mobile:request-42"})
    invalid = client.get("/health", headers={"X-Request-ID": "bad value with spaces"})

    assert supplied.headers["X-Request-ID"] == "mobile:request-42"
    assert invalid.headers["X-Request-ID"] != "bad value with spaces"
    assert len(invalid.headers["X-Request-ID"]) > 10
