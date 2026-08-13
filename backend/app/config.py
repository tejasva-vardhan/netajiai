"""Validated configuration for the greenfield backend.

Configuration is intentionally explicit. Provider adapters must not silently
fall back to development behavior in production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse


Environment = Literal["development", "test", "staging", "production"]
WorkerRole = Literal["outbox", "events", "temporal", "evidence_cleanup"]


class ProductionConfigurationError(ValueError):
    """Raised when production would run with an unsafe or incomplete config."""


def _csv(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def _positive_int(value: str | None, *, name: str, default: int) -> int:
    raw = (value or str(default)).strip()
    parsed = int(raw)
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _positive_float(value: str | None, *, name: str, default: float) -> float:
    raw = (value or str(default)).strip()
    parsed = float(raw)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _ratio(value: str | None, *, name: str, default: float) -> float:
    parsed = _positive_float(value, name=name, default=default)
    if parsed > 1:
        raise ValueError(f"{name} must be at most 1")
    return parsed


def _boolean(value: str | None, *, name: str, default: bool) -> bool:
    raw = (value if value is not None else str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _is_absolute_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


@dataclass(frozen=True, slots=True)
class Settings:
    environment: Environment = "development"
    service_name: str = "ai-neta-api"
    composition_module: str = ""
    public_disclosure_enabled: bool = False
    public_disclosure_policy_version: str = "disclosure-policy.v1"
    public_transparency_enabled: bool = False
    public_transparency_policy_version: str = "transparency-policy.v1"
    issue_cluster_hmac_key: str = field(default="", repr=False)
    issue_cluster_policy_version: str = "issue-cluster.v1"
    issue_cluster_cell_precision: int = 3
    issue_cluster_window_hours: int = 72
    issue_cluster_max_accuracy_m: float = 100.0
    api_origins: tuple[str, ...] = ("http://localhost:3000",)
    database_url: str = ""
    ai_provider: str = "mistral"
    ai_model: str = "mistral-small-latest"
    mistral_api_key: str = field(default="", repr=False)
    deepgram_api_key: str = field(default="", repr=False)
    deepgram_model: str = "nova-3"
    deepgram_endpoint: str = "https://api.deepgram.com/v1/listen"
    ai_monthly_request_limit: int = 1000
    voice_monthly_request_limit: int = 250
    budget_limits_configured: bool = field(default=False, repr=False)
    digilocker_mode: str = "sandbox"
    identity_provider: str = "temporary"
    digilocker_client_id: str = ""
    digilocker_client_secret: str = ""
    digilocker_authorization_endpoint: str = ""
    digilocker_token_endpoint: str = ""
    digilocker_user_endpoint: str = ""
    digilocker_redirect_uri: str = ""
    digilocker_scope: str = ""
    digilocker_purpose: str = "verification"
    identity_state_encryption_key: str = ""
    public_tracking_token_secret: str = ""
    oidc_issuer: str = ""
    oidc_jwks_url: str = ""
    oidc_audience: str = ""
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    oidc_identity_verified_claim: str = "identity_verified"
    temporal_target: str = ""
    temporal_namespace: str = ""
    temporal_api_key: str = ""
    temporal_task_queue: str = "ai-neta-complaints"
    kafka_bootstrap_servers: str = "kafka:29092"
    kafka_topic: str = "complaint.lifecycle.v1"
    kafka_consumer_group: str = "aineta-workflows"
    event_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 50
    outbox_poll_interval_seconds: float = 2.0
    outbox_error_backoff_seconds: float = 10.0
    evidence_cleanup_batch_size: int = 100
    evidence_cleanup_interval_seconds: float = 300.0
    evidence_cleanup_age_seconds: float = 86_400.0
    evidence_cleanup_retry_after_seconds: float = 900.0
    dev_safe_inbox: str = ""
    object_storage_provider: str = "s3"
    object_storage_bucket: str = "aineta-evidence"
    object_storage_region: str = "us-east-1"
    object_storage_endpoint: str = ""
    object_storage_presign_endpoint: str = ""
    redis_url: str = "redis://redis:6379/0"
    capture_attestation_mode: str = "unconfigured"
    web_capture_enabled: bool = False
    web_capture_session_hmac_key: str = field(default="", repr=False)
    web_capture_session_ttl_seconds: int = 300
    web_capture_review_required: bool = True
    media_inspector_mode: str = "unconfigured"
    otel_enabled: bool = False
    otel_exporter: str = "none"
    otel_exporter_endpoint: str = ""
    otel_sample_ratio: float = 1.0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        values = os.environ if environ is None else environ
        raw_environment = values.get("APP_ENV", "development").strip().lower()
        if raw_environment not in {"development", "test", "staging", "production"}:
            raise ValueError("APP_ENV must be development, test, staging, or production")

        return cls(
            environment=raw_environment,  # type: ignore[arg-type]
            service_name=values.get("SERVICE_NAME", "ai-neta-api").strip(),
            composition_module=values.get("COMPOSITION_MODULE", "").strip(),
            public_disclosure_enabled=_boolean(
                values.get("PUBLIC_DISCLOSURE_ENABLED"),
                name="PUBLIC_DISCLOSURE_ENABLED",
                default=False,
            ),
            public_disclosure_policy_version=values.get(
                "PUBLIC_DISCLOSURE_POLICY_VERSION", "disclosure-policy.v1"
            ).strip(),
            public_transparency_enabled=_boolean(
                values.get("PUBLIC_TRANSPARENCY_ENABLED"),
                name="PUBLIC_TRANSPARENCY_ENABLED",
                default=False,
            ),
            public_transparency_policy_version=values.get(
                "PUBLIC_TRANSPARENCY_POLICY_VERSION", "transparency-policy.v1"
            ).strip(),
            issue_cluster_hmac_key=values.get("ISSUE_CLUSTER_HMAC_KEY", "").strip(),
            issue_cluster_policy_version=values.get(
                "ISSUE_CLUSTER_POLICY_VERSION", "issue-cluster.v1"
            ).strip(),
            issue_cluster_cell_precision=_positive_int(
                values.get("ISSUE_CLUSTER_CELL_PRECISION"),
                name="ISSUE_CLUSTER_CELL_PRECISION",
                default=3,
            ),
            issue_cluster_window_hours=_positive_int(
                values.get("ISSUE_CLUSTER_WINDOW_HOURS"),
                name="ISSUE_CLUSTER_WINDOW_HOURS",
                default=72,
            ),
            issue_cluster_max_accuracy_m=_positive_float(
                values.get("ISSUE_CLUSTER_MAX_ACCURACY_M"),
                name="ISSUE_CLUSTER_MAX_ACCURACY_M",
                default=100.0,
            ),
            api_origins=_csv(values.get("ALLOWED_ORIGINS"))
            or ("http://localhost:3000",),
            database_url=values.get("DATABASE_URL", "").strip(),
            ai_provider=values.get("AI_PROVIDER", "mistral").strip().lower(),
            ai_model=values.get("AI_MODEL", "mistral-small-latest").strip(),
            mistral_api_key=values.get("MISTRAL_API_KEY", "").strip(),
            deepgram_api_key=values.get("DEEPGRAM_API_KEY", "").strip(),
            deepgram_model=values.get("DEEPGRAM_MODEL", "nova-3").strip(),
            deepgram_endpoint=values.get(
                "DEEPGRAM_ENDPOINT", "https://api.deepgram.com/v1/listen"
            ).strip(),
            ai_monthly_request_limit=_positive_int(
                values.get("AI_MONTHLY_REQUEST_LIMIT"),
                name="AI_MONTHLY_REQUEST_LIMIT",
                default=1000,
            ),
            voice_monthly_request_limit=_positive_int(
                values.get("VOICE_MONTHLY_REQUEST_LIMIT"),
                name="VOICE_MONTHLY_REQUEST_LIMIT",
                default=250,
            ),
            budget_limits_configured=bool(
                values.get("AI_MONTHLY_REQUEST_LIMIT", "").strip()
                and values.get("VOICE_MONTHLY_REQUEST_LIMIT", "").strip()
            ),
            digilocker_mode=values.get("DIGILOCKER_MODE", "sandbox").strip().lower(),
            identity_provider=values.get("IDENTITY_PROVIDER", "temporary").strip().lower(),
            digilocker_client_id=values.get("DIGILOCKER_CLIENT_ID", "").strip(),
            digilocker_client_secret=values.get("DIGILOCKER_CLIENT_SECRET", "").strip(),
            digilocker_authorization_endpoint=values.get(
                "DIGILOCKER_AUTHORIZATION_ENDPOINT", ""
            ).strip(),
            digilocker_token_endpoint=values.get("DIGILOCKER_TOKEN_ENDPOINT", "").strip(),
            digilocker_user_endpoint=values.get("DIGILOCKER_USER_ENDPOINT", "").strip(),
            digilocker_redirect_uri=values.get("DIGILOCKER_REDIRECT_URI", "").strip(),
            digilocker_scope=values.get("DIGILOCKER_SCOPE", "").strip(),
            digilocker_purpose=values.get("DIGILOCKER_PURPOSE", "verification").strip().lower(),
            identity_state_encryption_key=values.get(
                "IDENTITY_STATE_ENCRYPTION_KEY", ""
            ).strip(),
            public_tracking_token_secret=values.get(
                "PUBLIC_TRACKING_TOKEN_SECRET", ""
            ).strip(),
            oidc_issuer=values.get("OIDC_ISSUER", "").strip(),
            oidc_jwks_url=values.get("OIDC_JWKS_URL", "").strip(),
            oidc_audience=values.get("OIDC_AUDIENCE", "").strip(),
            oidc_algorithms=_csv(values.get("OIDC_ALGORITHMS")) or ("RS256",),
            oidc_identity_verified_claim=values.get(
                "OIDC_IDENTITY_VERIFIED_CLAIM", "identity_verified"
            ).strip(),
            temporal_target=values.get("TEMPORAL_TARGET", "").strip(),
            temporal_namespace=values.get("TEMPORAL_NAMESPACE", "").strip(),
            temporal_api_key=values.get("TEMPORAL_API_KEY", "").strip(),
            temporal_task_queue=values.get(
                "TEMPORAL_TASK_QUEUE", "ai-neta-complaints"
            ).strip(),
            kafka_bootstrap_servers=values.get(
                "KAFKA_BOOTSTRAP_SERVERS", "kafka:29092"
            ).strip(),
            kafka_topic=values.get(
                "KAFKA_TOPIC", "complaint.lifecycle.v1"
            ).strip(),
            kafka_consumer_group=values.get(
                "KAFKA_CONSUMER_GROUP", "aineta-workflows"
            ).strip(),
            event_poll_interval_seconds=_positive_float(
                values.get("EVENT_POLL_INTERVAL_SECONDS"),
                name="EVENT_POLL_INTERVAL_SECONDS",
                default=1.0,
            ),
            outbox_batch_size=_positive_int(
                values.get("OUTBOX_BATCH_SIZE"),
                name="OUTBOX_BATCH_SIZE",
                default=50,
            ),
            outbox_poll_interval_seconds=_positive_float(
                values.get("OUTBOX_POLL_INTERVAL_SECONDS"),
                name="OUTBOX_POLL_INTERVAL_SECONDS",
                default=2.0,
            ),
            outbox_error_backoff_seconds=_positive_float(
                values.get("OUTBOX_ERROR_BACKOFF_SECONDS"),
                name="OUTBOX_ERROR_BACKOFF_SECONDS",
                default=10.0,
            ),
            evidence_cleanup_batch_size=_positive_int(
                values.get("EVIDENCE_CLEANUP_BATCH_SIZE"),
                name="EVIDENCE_CLEANUP_BATCH_SIZE",
                default=100,
            ),
            evidence_cleanup_interval_seconds=_positive_float(
                values.get("EVIDENCE_CLEANUP_INTERVAL_SECONDS"),
                name="EVIDENCE_CLEANUP_INTERVAL_SECONDS",
                default=300.0,
            ),
            evidence_cleanup_age_seconds=_positive_float(
                values.get("EVIDENCE_CLEANUP_AGE_SECONDS"),
                name="EVIDENCE_CLEANUP_AGE_SECONDS",
                default=86_400.0,
            ),
            evidence_cleanup_retry_after_seconds=_positive_float(
                values.get("EVIDENCE_CLEANUP_RETRY_AFTER_SECONDS"),
                name="EVIDENCE_CLEANUP_RETRY_AFTER_SECONDS",
                default=900.0,
            ),
            dev_safe_inbox=values.get("DEV_SAFE_INBOX", "").strip(),
            object_storage_provider=values.get(
                "OBJECT_STORAGE_PROVIDER", "s3"
            ).strip().lower(),
            object_storage_bucket=values.get(
                "OBJECT_STORAGE_BUCKET", "aineta-evidence"
            ).strip(),
            object_storage_region=values.get(
                "OBJECT_STORAGE_REGION", "us-east-1"
            ).strip(),
            object_storage_endpoint=values.get("OBJECT_STORAGE_ENDPOINT", "").strip(),
            object_storage_presign_endpoint=values.get(
                "OBJECT_STORAGE_PRESIGN_ENDPOINT", ""
            ).strip(),
            redis_url=values.get("REDIS_URL", "redis://redis:6379/0").strip(),
            capture_attestation_mode=values.get(
                "CAPTURE_ATTESTATION_MODE", "unconfigured"
            ).strip().lower(),
            web_capture_enabled=_boolean(
                values.get("WEB_CAPTURE_ENABLED"),
                name="WEB_CAPTURE_ENABLED",
                default=False,
            ),
            web_capture_session_hmac_key=values.get(
                "WEB_CAPTURE_SESSION_HMAC_KEY", ""
            ).strip(),
            web_capture_session_ttl_seconds=_positive_int(
                values.get("WEB_CAPTURE_SESSION_TTL_SECONDS"),
                name="WEB_CAPTURE_SESSION_TTL_SECONDS",
                default=300,
            ),
            web_capture_review_required=_boolean(
                values.get("WEB_CAPTURE_REVIEW_REQUIRED"),
                name="WEB_CAPTURE_REVIEW_REQUIRED",
                default=True,
            ),
            media_inspector_mode=values.get("MEDIA_INSPECTOR_MODE", "unconfigured")
            .strip()
            .lower(),
            otel_enabled=_boolean(
                values.get("OTEL_ENABLED"), name="OTEL_ENABLED", default=False
            ),
            otel_exporter=values.get("OTEL_EXPORTER", "none").strip().lower(),
            otel_exporter_endpoint=values.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip(),
            otel_sample_ratio=_ratio(
                values.get("OTEL_SAMPLE_RATIO"), name="OTEL_SAMPLE_RATIO", default=1.0
            ),
        )

    def validate_for_production(self) -> None:
        """Reject configurations that would silently use demo behavior."""

        if self.environment not in {"staging", "production"}:
            return
        if not self.budget_limits_configured:
            raise ProductionConfigurationError(
                "AI_MONTHLY_REQUEST_LIMIT and VOICE_MONTHLY_REQUEST_LIMIT must be explicitly configured"
            )
        if self.environment != "production":
            return

        required = {
            "DATABASE_URL": self.database_url,
            "COMPOSITION_MODULE": self.composition_module,
            "AI_PROVIDER": self.ai_provider,
            "AI_MODEL": self.ai_model,
            "MISTRAL_API_KEY": self.mistral_api_key,
            "DEEPGRAM_API_KEY": self.deepgram_api_key,
            "IDENTITY_PROVIDER": self.identity_provider,
            "DIGILOCKER_MODE": self.digilocker_mode,
            "DIGILOCKER_CLIENT_ID": self.digilocker_client_id,
            "DIGILOCKER_CLIENT_SECRET": self.digilocker_client_secret,
            "DIGILOCKER_AUTHORIZATION_ENDPOINT": self.digilocker_authorization_endpoint,
            "DIGILOCKER_TOKEN_ENDPOINT": self.digilocker_token_endpoint,
            "DIGILOCKER_USER_ENDPOINT": self.digilocker_user_endpoint,
            "DIGILOCKER_REDIRECT_URI": self.digilocker_redirect_uri,
            "DIGILOCKER_SCOPE": self.digilocker_scope,
            "DIGILOCKER_PURPOSE": self.digilocker_purpose,
            "IDENTITY_STATE_ENCRYPTION_KEY": self.identity_state_encryption_key,
            "PUBLIC_TRACKING_TOKEN_SECRET": self.public_tracking_token_secret,
            "ISSUE_CLUSTER_HMAC_KEY": self.issue_cluster_hmac_key,
            "OIDC_ISSUER": self.oidc_issuer,
            "OIDC_JWKS_URL": self.oidc_jwks_url,
            "OIDC_AUDIENCE": self.oidc_audience,
            "OIDC_IDENTITY_VERIFIED_CLAIM": self.oidc_identity_verified_claim,
            "TEMPORAL_TARGET": self.temporal_target,
            "TEMPORAL_NAMESPACE": self.temporal_namespace,
            "TEMPORAL_API_KEY": self.temporal_api_key,
            "TEMPORAL_TASK_QUEUE": self.temporal_task_queue,
            "KAFKA_BOOTSTRAP_SERVERS": self.kafka_bootstrap_servers,
            "KAFKA_TOPIC": self.kafka_topic,
            "KAFKA_CONSUMER_GROUP": self.kafka_consumer_group,
            "OBJECT_STORAGE_PROVIDER": self.object_storage_provider,
            "OBJECT_STORAGE_BUCKET": self.object_storage_bucket,
            "OBJECT_STORAGE_REGION": self.object_storage_region,
            "CAPTURE_ATTESTATION_MODE": self.capture_attestation_mode,
            "MEDIA_INSPECTOR_MODE": self.media_inspector_mode,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ProductionConfigurationError(
                "Missing required production configuration: " + ", ".join(missing)
            )
        if self.ai_provider != "mistral":
            raise ProductionConfigurationError("AI_PROVIDER=mistral is required")
        if not self.mistral_api_key:
            raise ProductionConfigurationError("MISTRAL_API_KEY is required")
        if not self.deepgram_api_key:
            raise ProductionConfigurationError("DEEPGRAM_API_KEY is required")
        if self.ai_provider == "fake":
            raise ProductionConfigurationError("AI_PROVIDER=fake is not allowed in production")
        if self.ai_monthly_request_limit < 1 or self.voice_monthly_request_limit < 1:
            raise ProductionConfigurationError(
                "AI_MONTHLY_REQUEST_LIMIT and VOICE_MONTHLY_REQUEST_LIMIT must be positive"
            )
        if self.public_disclosure_enabled and not self.public_disclosure_policy_version:
            raise ProductionConfigurationError(
                "PUBLIC_DISCLOSURE_POLICY_VERSION is required when public disclosure is enabled"
            )
        if self.public_transparency_enabled and not self.public_transparency_policy_version:
            raise ProductionConfigurationError(
                "PUBLIC_TRANSPARENCY_POLICY_VERSION is required when public transparency is enabled"
            )
        if len(self.issue_cluster_hmac_key.encode("utf-8")) < 32:
            raise ProductionConfigurationError(
                "ISSUE_CLUSTER_HMAC_KEY must be at least 32 bytes in production"
            )
        if not 1 <= self.issue_cluster_cell_precision <= 6:
            raise ProductionConfigurationError(
                "ISSUE_CLUSTER_CELL_PRECISION must be between 1 and 6"
            )
        if self.digilocker_mode != "requester":
            raise ProductionConfigurationError(
                "DIGILOCKER_MODE=requester is required for production"
            )
        if self.identity_provider != "digilocker":
            raise ProductionConfigurationError(
                "IDENTITY_PROVIDER=digilocker is required for production"
            )
        for name, endpoint in {
            "DIGILOCKER_AUTHORIZATION_ENDPOINT": self.digilocker_authorization_endpoint,
            "DIGILOCKER_TOKEN_ENDPOINT": self.digilocker_token_endpoint,
            "DIGILOCKER_USER_ENDPOINT": self.digilocker_user_endpoint,
            "DIGILOCKER_REDIRECT_URI": self.digilocker_redirect_uri,
            "OIDC_ISSUER": self.oidc_issuer,
            "OIDC_JWKS_URL": self.oidc_jwks_url,
        }.items():
            if not _is_absolute_https_url(endpoint):
                raise ProductionConfigurationError(
                    f"{name} must be an absolute HTTPS URL in production"
                )
        if self.digilocker_purpose not in {
            "kyc",
            "verification",
            "compliance",
            "availing_services",
            "educational",
        }:
            raise ProductionConfigurationError(
                "DIGILOCKER_PURPOSE is not an approved Requester purpose"
            )
        if any(algorithm not in {"RS256", "ES256", "EdDSA"} for algorithm in self.oidc_algorithms):
            raise ProductionConfigurationError(
                "OIDC_ALGORITHMS must use an approved asymmetric algorithm"
            )
        if self.object_storage_provider != "s3":
            raise ProductionConfigurationError(
                "OBJECT_STORAGE_PROVIDER=s3 is required in production"
            )
        if self.capture_attestation_mode == "unconfigured":
            raise ProductionConfigurationError(
                "CAPTURE_ATTESTATION_MODE must select a production verifier"
            )
        if self.web_capture_enabled:
            if len(self.web_capture_session_hmac_key.encode("utf-8")) < 32:
                raise ProductionConfigurationError(
                    "WEB_CAPTURE_SESSION_HMAC_KEY must be at least 32 bytes when web capture is enabled"
                )
            if self.web_capture_session_ttl_seconds > 900:
                raise ProductionConfigurationError(
                    "WEB_CAPTURE_SESSION_TTL_SECONDS must be at most 900 seconds"
                )
        if self.media_inspector_mode == "unconfigured":
            raise ProductionConfigurationError(
                "MEDIA_INSPECTOR_MODE must select a production inspector"
            )
        if self.capture_attestation_mode in {"fixture", "fake", "memory"}:
            raise ProductionConfigurationError(
                "Test capture attestation modes are not allowed in production"
            )
        if self.media_inspector_mode in {"fixture", "fake", "memory"}:
            raise ProductionConfigurationError(
                "Test media inspector modes are not allowed in production"
            )
        if (
            not self.api_origins
            or "*" in self.api_origins
            or any(not _is_absolute_https_url(origin) for origin in self.api_origins)
        ):
            raise ProductionConfigurationError(
                "ALLOWED_ORIGINS must contain explicit HTTPS production origins"
            )
        if not self.otel_enabled:
            raise ProductionConfigurationError(
                "OTEL_ENABLED=true is required for production"
            )
        if self.otel_exporter != "otlp_http":
            raise ProductionConfigurationError(
                "OTEL_EXPORTER=otlp_http is required for production"
            )
        parsed_otel_endpoint = urlparse(self.otel_exporter_endpoint)
        if (
            parsed_otel_endpoint.scheme not in {"http", "https"}
            or not parsed_otel_endpoint.netloc
        ):
            raise ProductionConfigurationError(
                "OTEL_EXPORTER_OTLP_ENDPOINT must be an absolute HTTP(S) URL"
            )

    def validate_for_worker(self, worker: WorkerRole) -> None:
        """Validate only the configuration needed by a separately deployed worker."""

        if self.environment not in {"staging", "production"}:
            return
        if not self.budget_limits_configured:
            raise ProductionConfigurationError(
                "AI_MONTHLY_REQUEST_LIMIT and VOICE_MONTHLY_REQUEST_LIMIT must be explicitly configured"
            )
        if self.environment != "production":
            return

        required_by_worker: dict[WorkerRole, dict[str, str]] = {
            "outbox": {
                "DATABASE_URL": self.database_url,
                "KAFKA_BOOTSTRAP_SERVERS": self.kafka_bootstrap_servers,
            },
            "events": {
                "KAFKA_BOOTSTRAP_SERVERS": self.kafka_bootstrap_servers,
                "KAFKA_TOPIC": self.kafka_topic,
                "KAFKA_CONSUMER_GROUP": self.kafka_consumer_group,
                "TEMPORAL_TARGET": self.temporal_target,
                "TEMPORAL_NAMESPACE": self.temporal_namespace,
                "TEMPORAL_API_KEY": self.temporal_api_key,
                "TEMPORAL_TASK_QUEUE": self.temporal_task_queue,
            },
            "temporal": {
                "DATABASE_URL": self.database_url,
                "TEMPORAL_TARGET": self.temporal_target,
                "TEMPORAL_NAMESPACE": self.temporal_namespace,
                "TEMPORAL_API_KEY": self.temporal_api_key,
                "TEMPORAL_TASK_QUEUE": self.temporal_task_queue,
            },
            "evidence_cleanup": {
                "DATABASE_URL": self.database_url,
                "OBJECT_STORAGE_PROVIDER": self.object_storage_provider,
                "OBJECT_STORAGE_BUCKET": self.object_storage_bucket,
                "OBJECT_STORAGE_REGION": self.object_storage_region,
            },
        }
        missing = [name for name, value in required_by_worker[worker].items() if not value]
        if missing:
            raise ProductionConfigurationError(
                f"Missing required production configuration for {worker} worker: "
                + ", ".join(missing)
            )

        if worker == "evidence_cleanup" and self.object_storage_provider != "s3":
            raise ProductionConfigurationError(
                "OBJECT_STORAGE_PROVIDER=s3 is required for the evidence cleanup worker"
            )
