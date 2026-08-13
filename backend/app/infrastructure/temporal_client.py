"""Provider-neutral Temporal client connection construction."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from temporalio.client import Client

from backend.app.config import Settings


TemporalClientConnector = Callable[..., Awaitable[Client]]


def temporal_connect_kwargs(settings: Settings) -> dict[str, object]:
    """Return explicit SDK options without exposing credentials in logs."""

    if not settings.temporal_target.strip():
        raise ValueError("TEMPORAL_TARGET is required")
    namespace = settings.temporal_namespace.strip() or "default"
    return {
        "target_host": settings.temporal_target,
        "namespace": namespace,
        **({"api_key": settings.temporal_api_key} if settings.temporal_api_key else {}),
    }


async def connect_temporal(settings: Settings, *, connector: TemporalClientConnector = Client.connect) -> Client:
    """Connect to the configured Temporal service using API-key TLS defaults."""

    kwargs = temporal_connect_kwargs(settings)
    return await connector(**kwargs)
