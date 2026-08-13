"""Concrete provider graph for the local AI Neta deployment.

The application is assembled once here. Domain and application services keep
their provider-neutral ports; this module owns the selected local services and
the temporary identity path used before DigiLocker Requester approval.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import redis.asyncio as redis_asyncio
from sqlalchemy import select

from backend.app.application.rate_limits import RedisRateLimiter
from backend.app.application.sla import SyntheticSlaPolicy
from backend.app.application.routing import RoutingDecision
from backend.app.config import Settings
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.infrastructure.ai import build_agno_orchestrator
from backend.app.infrastructure.auth import OidcBearerTokenVerifier
from backend.app.infrastructure.browser_capture import BrowserCaptureSessionSigner
from backend.app.infrastructure.closure import FixtureClosureProofVerifier
from backend.app.infrastructure.db import ComplaintEvidenceRecord, ComplaintRecord
from backend.app.infrastructure.digilocker import (
    HttpDigiLockerAuthorizationTransport,
    TemporaryLocalIdentityTransport,
)
from backend.app.infrastructure.evidence_capture import LocalCaptureAttestationVerifier, LocalMediaInspector
from backend.app.infrastructure.identity import SandboxDigiLockerVerifier
from backend.app.infrastructure.identity_authorization import (
    build_identity_authorization_service_factory,
)
from backend.app.infrastructure.routing import SyntheticMpRoutingResolver
from backend.app.infrastructure.session import create_session_factory
from backend.app.infrastructure.speech import DeepgramSpeechToText
from backend.app.infrastructure.storage import S3ObjectStore
from backend.app.infrastructure.temporal import TemporalComplaintWorkflowSignalSender
from backend.app.infrastructure.temporal_client import connect_temporal
from backend.app.infrastructure.tracking import HmacPublicTrackingTokenCodec
from backend.app.runtime import RuntimeAdapters


class DatabaseRoutingResolver:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def resolve(
        self,
        principal: AuthenticatedPrincipal,
        evidence_asset_ids: tuple[UUID, ...],
    ) -> RoutingDecision:
        with self._session_factory() as session:
            return SyntheticMpRoutingResolver(session).resolve(
                principal, evidence_asset_ids
            )


class DatabaseRoutingActivationResolver:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def resolve(self, complaint_id: UUID) -> RoutingDecision:
        with self._session_factory() as session:
            complaint = session.get(ComplaintRecord, complaint_id)
            if complaint is None:
                raise LookupError("Complaint was not found")
            evidence_ids = tuple(
                session.scalars(
                    select(ComplaintEvidenceRecord.evidence_asset_id).where(
                        ComplaintEvidenceRecord.complaint_id == complaint_id
                    )
                ).all()
            )
            principal = AuthenticatedPrincipal(
                complaint.citizen_id,
                identity_verified=True,
            )
            return SyntheticMpRoutingResolver(session).resolve(principal, evidence_ids)


class LazyTemporalWorkflowSignals:
    """Connect to Temporal only when an API command actually sends a signal."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    async def _sender(self) -> TemporalComplaintWorkflowSignalSender:
        if self._client is None:
            self._client = await connect_temporal(self._settings)
        return TemporalComplaintWorkflowSignalSender(self._client)

    async def routing_activation(self, complaint_id: UUID, *, signal_id: UUID) -> None:
        await (await self._sender()).routing_activation(complaint_id, signal_id=signal_id)

    async def department_response(
        self,
        complaint_id: UUID,
        *,
        signal_id: UUID,
        outcome: str,
        proof_claim_id: UUID | None,
    ) -> None:
        await (await self._sender()).department_response(
            complaint_id,
            signal_id=signal_id,
            outcome=outcome,  # type: ignore[arg-type]
            proof_claim_id=proof_claim_id,
        )

    async def citizen_confirmation(
        self,
        complaint_id: UUID,
        *,
        signal_id: UUID,
        outcome: str,
    ) -> None:
        await (await self._sender()).citizen_confirmation(
            complaint_id,
            signal_id=signal_id,
            outcome=outcome,  # type: ignore[arg-type]
        )


def _identity_factory(settings: Settings) -> Any:
    transport: Any
    if settings.identity_provider == "temporary":
        transport = TemporaryLocalIdentityTransport(
            settings.identity_state_encryption_key
        )
    else:
        transport = HttpDigiLockerAuthorizationTransport(
            client_id=settings.digilocker_client_id,
            client_secret=settings.digilocker_client_secret,
            token_endpoint=settings.digilocker_token_endpoint,
            user_endpoint=settings.digilocker_user_endpoint,
        )
    return build_identity_authorization_service_factory(
        settings,
        transport=transport,
        verifier=SandboxDigiLockerVerifier(),
        allowed_claim_keys=frozenset(),
    )


def build_adapters(settings: Settings) -> RuntimeAdapters:
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required")
    if not settings.identity_state_encryption_key:
        raise ValueError("IDENTITY_STATE_ENCRYPTION_KEY is required")
    if settings.ai_provider != "mistral":
        raise ValueError("AI_PROVIDER=mistral is required by the local deployment")
    if not settings.mistral_api_key:
        raise ValueError("MISTRAL_API_KEY is required by the local deployment")
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY is required by the local deployment")

    session_factory = create_session_factory(settings.database_url)
    object_store = S3ObjectStore(
        settings.object_storage_bucket,
        region=settings.object_storage_region,
        endpoint_url=settings.object_storage_endpoint,
        presign_endpoint_url=settings.object_storage_presign_endpoint,
    )
    browser_capture = BrowserCaptureSessionSigner(
        settings.web_capture_session_hmac_key,
        ttl_seconds=settings.web_capture_session_ttl_seconds,
    )
    return RuntimeAdapters(
        session_factory=session_factory,
        principal_resolver=OidcBearerTokenVerifier(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_url=settings.oidc_jwks_url,
            algorithms=settings.oidc_algorithms,
            identity_verified_claim=settings.oidc_identity_verified_claim,
        ).authenticate,
        capture_verifier=LocalCaptureAttestationVerifier(browser_capture),
        capture_session_issuer=browser_capture,
        object_store=object_store,
        media_inspector=LocalMediaInspector(),
        identity_authorization_service_factory=_identity_factory(settings),
        tracking_token_codec=HmacPublicTrackingTokenCodec(
            settings.public_tracking_token_secret
        ),
        ai_orchestrator=build_agno_orchestrator(settings),
        routing_resolver=DatabaseRoutingResolver(session_factory),
        sla_policy=SyntheticSlaPolicy(),
        routing_activation_resolver=DatabaseRoutingActivationResolver(session_factory),
        workflow_signal_sender=LazyTemporalWorkflowSignals(settings),
        closure_proof_verifier=FixtureClosureProofVerifier(),
        speech_to_text=DeepgramSpeechToText(
            api_key=settings.deepgram_api_key,
            model=settings.deepgram_model,
            object_store=object_store,
            endpoint=settings.deepgram_endpoint,
        ),
        rate_limiter=RedisRateLimiter(
            redis_asyncio.from_url(  # type: ignore[arg-type]
                settings.redis_url, decode_responses=False
            )
        ),
    )
