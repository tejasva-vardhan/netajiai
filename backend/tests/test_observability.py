from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from collections.abc import Sequence
from starlette.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import ProductionConfigurationError, Settings
from backend.app.observability import Telemetry, TelemetryConfigurationError


class MemorySpanExporter(SpanExporter):
    """Small deterministic exporter kept local to the test suite."""

    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        del timeout_millis
        return True


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "composition_module": "deployment.adapters",
        "database_url": "postgresql+psycopg://example",
        "ai_provider": "mistral",
        "ai_model": "approved-model",
        "mistral_api_key": "mistral-test-key",
        "deepgram_api_key": "deepgram-test-key",
        "ai_monthly_request_limit": 1000,
        "voice_monthly_request_limit": 250,
        "budget_limits_configured": True,
        "digilocker_mode": "requester",
        "identity_provider": "digilocker",
        "digilocker_client_id": "client-id",
        "digilocker_client_secret": "secret",
        "digilocker_authorization_endpoint": "https://provider.example/authorize",
        "digilocker_token_endpoint": "https://provider.example/token",
        "digilocker_user_endpoint": "https://provider.example/user",
        "digilocker_redirect_uri": "https://app.example/auth/digilocker/callback",
        "digilocker_scope": "approved-scope",
        "identity_state_encryption_key": "test-encryption-key",
        "public_tracking_token_secret": "test-public-tracking-secret",
        "issue_cluster_hmac_key": "test-issue-cluster-hmac-key-32-bytes-long",
        "oidc_issuer": "https://issuer.example",
        "oidc_jwks_url": "https://issuer.example/.well-known/jwks.json",
        "oidc_audience": "ai-neta-api",
        "temporal_target": "temporal.example:7233",
        "temporal_namespace": "ai-neta",
        "temporal_api_key": "secret",
        "kafka_bootstrap_servers": "kafka.example:9092",
        "kafka_topic": "complaint.lifecycle.v1",
        "kafka_consumer_group": "aineta-workflows",
        "api_origins": ("https://app.example",),
        "object_storage_provider": "s3",
        "object_storage_bucket": "ai-neta-evidence",
        "object_storage_region": "ap-south-1",
        "capture_attestation_mode": "provider",
        "media_inspector_mode": "provider",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_disabled_telemetry_uses_noop_api_for_local_and_tests():
    telemetry = Telemetry.from_settings(Settings(environment="test"))

    assert telemetry.enabled is False
    telemetry.record_http_request(
        method="GET",
        route="/health",
        status_code=200,
        duration_seconds=0.001,
    )
    telemetry.shutdown()


def test_http_instrumentation_records_bounded_route_dimensions_without_body():
    span_exporter = MemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    telemetry = Telemetry.from_settings(
        Settings(environment="test", service_name="test-api", otel_enabled=True),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
    app = create_app(Settings(environment="test"), telemetry=telemetry)
    with TestClient(app) as client:
        response = client.get("/health?citizen_text=private-value")

    assert response.status_code == 200
    spans = span_exporter.spans
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/health"
    assert span.attributes["http.response.status_code"] == 200
    assert "private-value" not in str(span.attributes)
    assert "http.request.body" not in span.attributes
    metric_data = metric_reader.get_metrics_data()
    assert metric_data is not None
    metric_names = {
        metric.name
        for resource_metrics in metric_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    assert {
        "aineta.http.request.count",
        "aineta.http.request.duration",
    } <= metric_names


def test_production_requires_otlp_telemetry_configuration():
    settings = _production_settings()

    try:
        settings.validate_for_production()
    except ProductionConfigurationError as exc:
        assert "OTEL_ENABLED" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("production telemetry was optional")


def test_production_rejects_injected_disabled_telemetry():
    settings = _production_settings(
        otel_enabled=True,
        otel_exporter="otlp_http",
        otel_exporter_endpoint="https://collector.example",
    )

    try:
        create_app(settings, telemetry=Telemetry.disabled())
    except ProductionConfigurationError as exc:
        assert "enabled OpenTelemetry" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("disabled telemetry was accepted in production")


def test_enabled_telemetry_rejects_non_base_collector_url():
    settings = Settings(
        environment="test",
        otel_enabled=True,
        otel_exporter="otlp_http",
        otel_exporter_endpoint="https://collector.example/v1/traces?secret=1",
    )

    try:
        Telemetry.from_settings(settings)
    except TelemetryConfigurationError as exc:
        assert "base URL" in str(exc) or "query" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unsafe collector URL was accepted")
