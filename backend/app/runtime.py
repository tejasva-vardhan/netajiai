"""Deployment composition root for the greenfield API.

The application and domain layers expose provider ports, while deployment owns
the concrete adapters. Development and tests may use the raw ``create_app``
entrypoint with explicit fakes. Staging and production must load a
deployment-owned module through ``COMPOSITION_MODULE`` so a container cannot
silently boot with demo adapters or an incomplete provider graph.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from backend.app.api.main import create_app
from backend.app.config import ProductionConfigurationError, Settings
from backend.app.contracts.identity import AuthenticatedPrincipal


@dataclass(frozen=True, slots=True)
class RuntimeAdapters:
    """Concrete infrastructure adapters supplied by a deployment module."""

    session_factory: Callable[[], Any] | None = None
    principal_resolver: Callable[[str], AuthenticatedPrincipal] | None = None
    evidence_verifier: Any | None = None
    capture_verifier: Any | None = None
    capture_session_issuer: Any | None = None
    object_store: Any | None = None
    media_inspector: Any | None = None
    identity_authorization_service_factory: Callable[[Any], Any] | None = None
    tracking_token_codec: Any | None = None
    ai_orchestrator: Any | None = None
    routing_resolver: Any | None = None
    sla_policy: Any | None = None
    routing_activation_resolver: Any | None = None
    workflow_signal_sender: Any | None = None
    closure_proof_verifier: Any | None = None
    speech_to_text: Any | None = None
    rate_limiter: Any | None = None
    telemetry: Any | None = None

    def as_app_kwargs(self) -> dict[str, Any]:
        """Return the explicit injection arguments accepted by ``create_app``."""

        return {
            "session_factory": self.session_factory,
            "principal_resolver": self.principal_resolver,
            "evidence_verifier": self.evidence_verifier,
            "capture_verifier": self.capture_verifier,
            "capture_session_issuer": self.capture_session_issuer,
            "object_store": self.object_store,
            "media_inspector": self.media_inspector,
            "identity_authorization_service_factory": self.identity_authorization_service_factory,
            "tracking_token_codec": self.tracking_token_codec,
            "ai_orchestrator": self.ai_orchestrator,
            "routing_resolver": self.routing_resolver,
            "sla_policy": self.sla_policy,
            "routing_activation_resolver": self.routing_activation_resolver,
            "workflow_signal_sender": self.workflow_signal_sender,
            "closure_proof_verifier": self.closure_proof_verifier,
            "speech_to_text": self.speech_to_text,
            "rate_limiter": self.rate_limiter,
            "telemetry": self.telemetry,
        }


def load_runtime_adapters(settings: Settings) -> RuntimeAdapters:
    """Load the deployment-owned adapter factory named by configuration."""

    module_name = settings.composition_module.strip()
    if not module_name:
        raise ProductionConfigurationError(
            "COMPOSITION_MODULE is required for staging and production"
        )
    try:
        module = import_module(module_name)
    except (ImportError, ValueError) as exc:
        raise ProductionConfigurationError(
            "COMPOSITION_MODULE could not be imported"
        ) from exc
    factory = getattr(module, "build_adapters", None)
    if not callable(factory):
        raise ProductionConfigurationError(
            "COMPOSITION_MODULE must expose build_adapters(settings)"
        )
    try:
        adapters = factory(settings)
    except ProductionConfigurationError:
        raise
    except Exception as exc:
        raise ProductionConfigurationError(
            "The deployment adapter factory could not be constructed"
        ) from exc
    if not isinstance(adapters, RuntimeAdapters):
        raise ProductionConfigurationError(
            "build_adapters(settings) must return RuntimeAdapters"
        )
    return adapters


def build_application(
    settings: Settings | None = None,
    *,
    adapters: RuntimeAdapters | None = None,
) -> Any:
    """Build the API with an explicit provider graph for deployed environments."""

    config = settings or Settings.from_env()
    if config.environment in {"development", "staging", "production"} and config.composition_module:
        configured_adapters = adapters or load_runtime_adapters(config)
        return create_app(config, **configured_adapters.as_app_kwargs())
    if config.environment in {"staging", "production"}:
        configured_adapters = adapters or load_runtime_adapters(config)
        return create_app(config, **configured_adapters.as_app_kwargs())
    if adapters is None:
        return create_app(config)
    return create_app(config, **adapters.as_app_kwargs())


# This is the container/deployment entrypoint. Local development can continue
# using ``backend.app.api.main:app`` when it needs the deliberately unconfigured
# fail-closed API slice.
app = build_application()
