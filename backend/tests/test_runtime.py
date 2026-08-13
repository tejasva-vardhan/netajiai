import sys
import types

import pytest

from backend.app.config import ProductionConfigurationError, Settings
from backend.app.application.rate_limits import NoopRateLimiter, RateLimitDecision
from backend.app.application.sla import SyntheticSlaPolicy
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.runtime import RuntimeAdapters, build_application, load_runtime_adapters


class TestSharedRateLimiter:
    async def consume(
        self, *, key: str, limit: int, window_seconds: int
    ) -> RateLimitDecision:
        del key, window_seconds
        return RateLimitDecision(
            allowed=True, limit=limit, remaining=limit, retry_after_seconds=0
        )


def test_development_runtime_keeps_unconfigured_slice_explicit():
    application = build_application(Settings(environment="test"))

    assert application.title == "AI Neta API"


def test_deployed_runtime_requires_a_composition_module():
    with pytest.raises(ProductionConfigurationError, match="COMPOSITION_MODULE"):
        load_runtime_adapters(Settings(environment="staging"))


def test_staging_runtime_rejects_an_incomplete_explicit_bundle():
    with pytest.raises(
        ProductionConfigurationError, match="required staging/production adapters"
    ):
        build_application(
            Settings(environment="staging", budget_limits_configured=True),
            adapters=RuntimeAdapters(
                rate_limiter=TestSharedRateLimiter(),
                sla_policy=SyntheticSlaPolicy(),
            ),
        )


def test_staging_runtime_can_be_built_with_a_complete_explicit_bundle():
    application = build_application(
        Settings(environment="staging", budget_limits_configured=True),
        adapters=RuntimeAdapters(
            session_factory=lambda: None,
            principal_resolver=lambda _: AuthenticatedPrincipal("staging-test"),
            capture_verifier=object(),
            object_store=object(),
            media_inspector=object(),
            identity_authorization_service_factory=lambda _: object(),
            ai_orchestrator=object(),
            routing_resolver=object(),
            sla_policy=SyntheticSlaPolicy(),
            routing_activation_resolver=object(),
            workflow_signal_sender=object(),
            closure_proof_verifier=object(),
            speech_to_text=object(),
            rate_limiter=TestSharedRateLimiter(),
        ),
    )

    assert application.title == "AI Neta API"


def test_staging_runtime_rejects_process_local_rate_limiter():
    with pytest.raises(ProductionConfigurationError, match="shared rate_limiter"):
        build_application(
            Settings(environment="staging", budget_limits_configured=True),
            adapters=RuntimeAdapters(
                rate_limiter=NoopRateLimiter(), sla_policy=SyntheticSlaPolicy()
            ),
        )


def test_production_runtime_requires_injected_principal_resolver():
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://example",
        composition_module="deployment.adapters",
        ai_provider="mistral",
        ai_model="approved-model",
        mistral_api_key="mistral-test-key",
        deepgram_api_key="deepgram-test-key",
        budget_limits_configured=True,
        digilocker_mode="requester",
        identity_provider="digilocker",
        digilocker_client_id="client-id",
        digilocker_client_secret="secret",
        digilocker_authorization_endpoint="https://provider.example/authorize",
        digilocker_token_endpoint="https://provider.example/token",
        digilocker_user_endpoint="https://provider.example/user",
        digilocker_redirect_uri="https://app.example/auth/digilocker/callback",
        digilocker_scope="approved-scope",
        identity_state_encryption_key="test-encryption-key",
        public_tracking_token_secret="test-public-tracking-secret-32-bytes-long",
        issue_cluster_hmac_key="test-issue-cluster-hmac-key-32-bytes-long",
        oidc_issuer="https://issuer.example",
        oidc_jwks_url="https://issuer.example/.well-known/jwks.json",
        oidc_audience="ai-neta-api",
        temporal_target="temporal.example:7233",
        temporal_namespace="ai-neta",
        temporal_api_key="secret",
        kafka_bootstrap_servers="kafka.example:9092",
        kafka_topic="complaint.lifecycle.v1",
        kafka_consumer_group="aineta-workflows",
        api_origins=("https://app.example",),
        object_storage_provider="s3",
        object_storage_bucket="ai-neta-evidence",
        object_storage_region="ap-south-1",
        capture_attestation_mode="provider",
        media_inspector_mode="provider",
        otel_enabled=True,
        otel_exporter="otlp_http",
        otel_exporter_endpoint="https://otel.example",
    )

    with pytest.raises(ProductionConfigurationError, match="principal_resolver"):
        build_application(
            settings,
            adapters=RuntimeAdapters(
                rate_limiter=TestSharedRateLimiter(),
                sla_policy=object(),
            ),
        )


def test_runtime_loads_only_a_typed_adapter_bundle(monkeypatch):
    module = types.ModuleType("tests.runtime_adapters")

    def build_adapters(settings: Settings) -> RuntimeAdapters:
        assert settings.environment == "test"
        return RuntimeAdapters()

    module.build_adapters = build_adapters  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)

    adapters = load_runtime_adapters(
        Settings(environment="test", composition_module=module.__name__)
    )

    assert isinstance(adapters, RuntimeAdapters)
    assert adapters.as_app_kwargs()["session_factory"] is None


def test_runtime_rejects_untyped_factory_result(monkeypatch):
    module = types.ModuleType("tests.invalid_runtime_adapters")
    module.build_adapters = lambda settings: {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)

    with pytest.raises(ProductionConfigurationError, match="RuntimeAdapters"):
        load_runtime_adapters(
            Settings(environment="test", composition_module=module.__name__)
        )
