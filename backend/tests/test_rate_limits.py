import pytest
from fastapi.testclient import TestClient

from backend.app.ai.fakes import FakeAgentOrchestrator
from backend.app.api.main import create_app
from backend.app.application.rate_limits import (
    InMemoryRateLimiter,
    RateLimitPolicy,
    consume_global_budget,
)
from backend.app.config import Settings
from backend.app.contracts.identity import AuthenticatedPrincipal


@pytest.mark.asyncio
async def test_in_memory_limiter_returns_a_bounded_retry_decision():
    limiter = InMemoryRateLimiter()

    first = await limiter.consume(key="test-key", limit=2, window_seconds=60)
    second = await limiter.consume(key="test-key", limit=2, window_seconds=60)
    third = await limiter.consume(key="test-key", limit=2, window_seconds=60)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.remaining == 0
    assert third.retry_after_seconds >= 1


@pytest.mark.asyncio
async def test_global_budget_uses_a_shared_hashed_bucket():
    limiter = InMemoryRateLimiter()

    first = await consume_global_budget(limiter, budget_name="test-ai", limit=2)
    second = await consume_global_budget(limiter, budget_name="test-ai", limit=2)
    third = await consume_global_budget(limiter, budget_name="test-ai", limit=2)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.remaining == 0


def test_ai_route_returns_429_without_exposing_identity_or_ip_details():
    app = create_app(
        Settings(environment="test"),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "digilocker:rate-citizen", identity_verified=True
        ),
        ai_orchestrator=FakeAgentOrchestrator(),
        rate_limiter=InMemoryRateLimiter(),
    )
    app.state.rate_limit_policies = {
        "ai": RateLimitPolicy(
            identity_limit=2,
            ip_limit=100,
            device_limit=None,
            window_seconds=3600,
        )
    }
    client = TestClient(app)
    request = {
        "text": "Gali mein bada pothole hai",
        "language": "hi-IN",
    }
    headers = {"Authorization": "Bearer test-token"}

    assert client.post("/api/v1/complaints/draft", headers=headers, json=request).status_code == 200
    assert client.post("/api/v1/complaints/draft", headers=headers, json=request).status_code == 200
    limited = client.post("/api/v1/complaints/draft", headers=headers, json=request)

    assert limited.status_code == 429
    assert limited.headers["X-RateLimit-Remaining"] == "0"
    assert limited.headers["Retry-After"]
    assert limited.json() == {"detail": "Too many requests"}
    assert "digilocker:rate-citizen" not in limited.text
    assert "testclient" not in limited.text


def test_ai_route_enforces_a_fleet_wide_request_cap():
    app = create_app(
        Settings(environment="test", ai_monthly_request_limit=2),
        principal_resolver=lambda _: AuthenticatedPrincipal(
            "digilocker:budget-citizen", identity_verified=True
        ),
        ai_orchestrator=FakeAgentOrchestrator(),
        rate_limiter=InMemoryRateLimiter(),
    )
    app.state.rate_limit_policies = {
        "ai": RateLimitPolicy(
            identity_limit=100,
            ip_limit=100,
            device_limit=None,
            window_seconds=3600,
        )
    }
    client = TestClient(app)
    request = {"text": "Gali mein bada pothole hai", "language": "hi-IN"}
    headers = {"Authorization": "Bearer test-token"}

    assert client.post("/api/v1/complaints/draft", headers=headers, json=request).status_code == 200
    assert client.post("/api/v1/complaints/draft", headers=headers, json=request).status_code == 200
    limited = client.post("/api/v1/complaints/draft", headers=headers, json=request)

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Service usage limit reached"}
    assert "budget-citizen" not in limited.text
