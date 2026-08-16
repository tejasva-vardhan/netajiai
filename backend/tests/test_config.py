from dataclasses import replace

from backend.app.config import ProductionConfigurationError, Settings


def _production_env(**overrides: str) -> dict[str, str]:
    values = {
        "APP_ENV": "production",
        "COMPOSITION_MODULE": "deployment.adapters",
        "DATABASE_URL": "postgresql+psycopg://example",
        "AI_PROVIDER": "mistral",
        "AI_MODEL": "approved-model",
        "MISTRAL_API_KEY": "mistral-secret",
        "DEEPGRAM_API_KEY": "deepgram-secret",
        "AI_MONTHLY_REQUEST_LIMIT": "1000",
        "VOICE_MONTHLY_REQUEST_LIMIT": "250",
        "IDENTITY_PROVIDER": "digilocker",
        "DIGILOCKER_MODE": "requester",
        "DIGILOCKER_CLIENT_ID": "client-id",
        "DIGILOCKER_CLIENT_SECRET": "secret-from-test-manager",
        "DIGILOCKER_AUTHORIZATION_ENDPOINT": "https://provider.example/authorize",
        "DIGILOCKER_TOKEN_ENDPOINT": "https://provider.example/token",
        "DIGILOCKER_USER_ENDPOINT": "https://provider.example/user",
        "DIGILOCKER_REDIRECT_URI": "https://app.example/auth/digilocker/callback",
        "DIGILOCKER_SCOPE": "approved-scope",
        "IDENTITY_STATE_ENCRYPTION_KEY": "test-encryption-key",
        "PUBLIC_TRACKING_TOKEN_SECRET": "test-public-tracking-secret",
        "ISSUE_CLUSTER_HMAC_KEY": "test-issue-cluster-hmac-key-32-bytes-long",
        "OIDC_ISSUER": "https://issuer.example",
        "OIDC_JWKS_URL": "https://issuer.example/.well-known/jwks.json",
        "OIDC_AUDIENCE": "ai-neta-api",
        "OIDC_ALGORITHMS": "RS256",
        "TEMPORAL_TARGET": "temporal.example:7233",
        "TEMPORAL_NAMESPACE": "ai-neta",
        "TEMPORAL_API_KEY": "secret-from-test-manager",
        "TEMPORAL_TASK_QUEUE": "ai-neta-complaints",
        "KAFKA_BOOTSTRAP_SERVERS": "kafka.example:9092",
        "KAFKA_TOPIC": "complaint.lifecycle.v1",
        "KAFKA_CONSUMER_GROUP": "aineta-workflows",
        "ALLOWED_ORIGINS": "https://app.example",
        "OBJECT_STORAGE_PROVIDER": "s3",
        "OBJECT_STORAGE_BUCKET": "ai-neta-evidence",
        "OBJECT_STORAGE_REGION": "ap-south-1",
        "CAPTURE_ATTESTATION_MODE": "provider",
        "MEDIA_INSPECTOR_MODE": "provider",
    }
    values.update(overrides)
    return values


def test_development_defaults_are_safe_for_local_contract_work():
    settings = Settings.from_env({})

    assert settings.environment == "development"
    assert settings.ai_provider == "mistral"
    assert settings.ai_request_timeout_seconds == 12
    assert settings.kafka_bootstrap_servers == "kafka:29092"
    settings.validate_for_production()


def test_ai_request_timeout_is_positive_and_configurable():
    settings = Settings.from_env({"AI_REQUEST_TIMEOUT_SECONDS": "7"})

    assert settings.ai_request_timeout_seconds == 7

    try:
        Settings.from_env({"AI_REQUEST_TIMEOUT_SECONDS": "0"})
    except ValueError as exc:
        assert "AI_REQUEST_TIMEOUT_SECONDS" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-positive AI timeout was accepted")


def test_browser_capture_policy_defaults_to_review_and_parses_explicit_override():
    assert Settings.from_env({}).web_capture_review_required is True
    settings = Settings.from_env({"WEB_CAPTURE_REVIEW_REQUIRED": "false"})
    assert settings.web_capture_review_required is False


def test_public_transparency_defaults_off_and_requires_a_version_when_enabled():
    assert Settings.from_env({}).public_transparency_enabled is False
    settings = Settings.from_env(
        {
            "PUBLIC_TRANSPARENCY_ENABLED": "true",
            "PUBLIC_TRANSPARENCY_POLICY_VERSION": "transparency.v2",
        }
    )
    assert settings.public_transparency_enabled is True
    assert settings.public_transparency_policy_version == "transparency.v2"


def test_non_development_requires_explicit_ai_and_voice_budget_caps():
    settings = Settings.from_env({"APP_ENV": "staging"})

    try:
        settings.validate_for_production()
    except ProductionConfigurationError as exc:
        assert "AI_MONTHLY_REQUEST_LIMIT" in str(exc)
        assert "VOICE_MONTHLY_REQUEST_LIMIT" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("staging accepted implicit budget caps")


def test_production_rejects_fake_provider_and_missing_runtime_config():
    settings = Settings.from_env(
        {
            "APP_ENV": "production",
            "AI_PROVIDER": "fake",
            "AI_MONTHLY_REQUEST_LIMIT": "1000",
            "VOICE_MONTHLY_REQUEST_LIMIT": "250",
        }
    )

    try:
        settings.validate_for_production()
    except ProductionConfigurationError as exc:
        assert "DATABASE_URL" in str(exc)
        assert "MISTRAL_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unsafe production configuration was accepted")


def test_production_requires_explicit_origins_and_real_digilocker():
    settings = Settings.from_env(_production_env(ALLOWED_ORIGINS="*"))

    try:
        settings.validate_for_production()
    except ProductionConfigurationError as exc:
        assert "ALLOWED_ORIGINS" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("wildcard origins were accepted in production")

    local_default = replace(settings, api_origins=("http://localhost:3000",))
    try:
        local_default.validate_for_production()
    except ProductionConfigurationError as exc:
        assert "HTTPS production origins" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("development CORS origin was accepted in production")

    valid = replace(
        settings,
        api_origins=("https://app.example",),
        otel_enabled=True,
        otel_exporter="otlp_http",
        otel_exporter_endpoint="https://otel.example",
    )
    valid.validate_for_production()

    for field_name in ("oidc_issuer", "oidc_jwks_url"):
        invalid = replace(valid, **{field_name: "https://"})
        try:
            invalid.validate_for_production()
        except ProductionConfigurationError as exc:
            assert field_name.upper() in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"invalid {field_name} URL was accepted")


def test_production_requires_real_evidence_storage_and_inspection_modes():
    settings = Settings.from_env(_production_env(OBJECT_STORAGE_PROVIDER="memory"))

    try:
        settings.validate_for_production()
    except ProductionConfigurationError as exc:
        assert "OBJECT_STORAGE_PROVIDER=s3" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-production evidence storage was accepted")


def test_production_requires_mistral_secret():
    settings = Settings.from_env(_production_env(MISTRAL_API_KEY=""))

    try:
        settings.validate_for_production()
    except ProductionConfigurationError as exc:
        assert "MISTRAL_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Mistral production configuration without a key was accepted")


def test_production_worker_validation_matches_runtime_secret_scopes():
    Settings(
        environment="production",
        budget_limits_configured=True,
        database_url="postgresql+psycopg://example",
        kafka_bootstrap_servers="kafka.example:9092",
    ).validate_for_worker("outbox")

    Settings(
        environment="production",
        budget_limits_configured=True,
        kafka_bootstrap_servers="kafka.example:9092",
        kafka_topic="complaint.lifecycle.v1",
        kafka_consumer_group="aineta-workflows",
        temporal_target="temporal.example:7233",
        temporal_namespace="ai-neta",
        temporal_api_key="secret",
        temporal_task_queue="ai-neta-complaints",
    ).validate_for_worker("events")

    Settings(
        environment="production",
        budget_limits_configured=True,
        database_url="postgresql+psycopg://example",
        object_storage_provider="s3",
        object_storage_bucket="ai-neta-evidence",
        object_storage_region="ap-south-1",
    ).validate_for_worker("evidence_cleanup")

    try:
        Settings(
            environment="production",
            budget_limits_configured=True,
            database_url="postgresql+psycopg://example",
        ).validate_for_worker("temporal")
    except ProductionConfigurationError as exc:
        assert "TEMPORAL_TARGET" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Temporal worker accepted incomplete runtime configuration")
