"""FastAPI dependency boundaries for identity and persistence."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.contracts.identity import AuthenticatedPrincipal, AuthenticationError
from backend.app.application.complaints import (
    ComplaintSubmissionService,
    ComplaintTransitionService,
    ComplaintTrackingService,
    PublicComplaintTrackingService,
    EvidenceVerifier,
)
from backend.app.application.evidence import EvidenceUploadService
from backend.app.application.evidence_review import EvidenceReviewService
from backend.app.application.drafts import ComplaintDraftService
from backend.app.application.voice_drafts import VoiceDraftService
from backend.app.application.rate_limits import (
    DEFAULT_RATE_LIMIT_POLICIES,
    NoopRateLimiter,
    RateLimitExceeded,
    RateLimitPolicy,
    RateLimitUnavailable,
    RateLimiter,
    consume_global_budget,
    hashed_limit_key,
)
from backend.app.application.identity import IdentityVerificationStatusService
from backend.app.application.disclosure import DisclosureConsentService
from backend.app.application.issue_clusters import IssueClusterPolicy
from backend.app.application.admin import AdminComplaintQueryService
from backend.app.application.authorization import has_capability
from backend.app.application.conversation import ConversationService
from backend.app.application.workflow_signals import WorkflowSignalService
from backend.app.application.routing_activation import RoutingActivationService
from backend.app.application.sla import SyntheticSlaPolicy
from backend.app.application.schemes import SchemeKnowledgeService, SchemeReviewService
from backend.app.application.transparency import PublicTransparencyService
from backend.app.infrastructure.sessions import SqlAlchemyConversationSessionRepository
from backend.app.infrastructure.workflow_signals import (
    SqlAlchemyCitizenResolutionRepository,
    SqlAlchemyWorkflowSignalRepository,
)
from backend.app.infrastructure.department_replies import SqlAlchemyDepartmentReplyRepository
from backend.app.infrastructure.closure import (
    SqlAlchemyClosureProofRepository,
    UnconfiguredClosureProofVerifier,
)
from backend.app.infrastructure.schemes import SqlAlchemySchemeKnowledgeRepository
from backend.app.application.ports import AgentOrchestrator
from backend.app.infrastructure.evidence_capture import (
    UnconfiguredCaptureAttestationVerifier,
    UnconfiguredMediaInspector,
)
from backend.app.infrastructure.evidence import SqlAlchemyEvidenceVerifier
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository
from backend.app.infrastructure.evidence_repositories import SqlAlchemyEvidenceMetadataRepository
from backend.app.infrastructure.speech import UnconfiguredSpeechToText
from backend.app.infrastructure.voice_drafts import SqlAlchemyVoiceDraftRequestRepository
from backend.app.infrastructure.identity_repositories import SqlAlchemyIdentityVerificationRepository
from backend.app.infrastructure.storage import UnconfiguredObjectStore


def get_current_principal(request: Request) -> AuthenticatedPrincipal:
    """Resolve identity through the configured auth adapter.

    The default deliberately fails closed. Tests and a future auth adapter may
    override this dependency; clients cannot supply a citizen ID in a body.
    """

    resolver = getattr(request.app.state, "principal_resolver", None)
    if resolver is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return resolver(request.headers.get("Authorization", ""))
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_operator_principal(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> AuthenticatedPrincipal:
    if not has_capability(principal, "admin.read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An operator capability is required",
        )
    return principal


def get_verified_principal(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> AuthenticatedPrincipal:
    """Use the persisted DigiLocker result when the token has not refreshed.

    The OIDC claim is a useful fast path, but the verification record created by
    this service is the server-owned authority after a DigiLocker handoff. This
    also avoids requiring a citizen to obtain a new access token immediately
    after returning from the provider.
    """

    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return principal
    try:
        with session_factory() as session:
            return _principal_with_persisted_verification(principal, session)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity verification status is temporarily unavailable",
        ) from exc


def _principal_with_persisted_verification(
    principal: AuthenticatedPrincipal, session: Session
) -> AuthenticatedPrincipal:
    verification_status = IdentityVerificationStatusService(
        SqlAlchemyIdentityVerificationRepository(session)
    ).get(principal)
    if verification_status.status == "verified":
        return replace(principal, identity_verified=True)
    if verification_status.verification_id is not None:
        # A persisted pending, rejected, or expired DigiLocker result is the
        # server-owned revocation boundary; a stale token claim cannot bypass it.
        return replace(principal, identity_verified=False)
    # Preserve the OIDC claim only when no server-side DigiLocker record exists.
    return principal


async def _enforce_rate_limit(
    request: Request,
    *,
    policy_name: str,
    principal: AuthenticatedPrincipal | None,
) -> None:
    limiter: RateLimiter = getattr(request.app.state, "rate_limiter", None) or NoopRateLimiter()
    policies: dict[str, RateLimitPolicy] = getattr(
        request.app.state, "rate_limit_policies", DEFAULT_RATE_LIMIT_POLICIES
    )
    policy = policies.get(policy_name)
    if policy is None:
        raise HTTPException(status_code=503, detail="Rate-limit policy is not configured")
    dimensions: list[tuple[str, str, int | None]] = [
        ("ip", request.client.host if request.client else "unknown", policy.ip_limit),
    ]
    if principal is not None:
        dimensions.append(("identity", principal.subject_ref, policy.identity_limit))
    device_id = request.headers.get("X-Device-ID", "").strip()
    if device_id and len(device_id) <= 255 and policy.device_limit is not None:
        dimensions.append(("device", device_id, policy.device_limit))
    try:
        for dimension, value, limit in dimensions:
            if limit is None or limit <= 0:
                continue
            decision = await limiter.consume(
                key=hashed_limit_key(policy=policy_name, dimension=dimension, value=value),
                limit=limit,
                window_seconds=policy.window_seconds,
            )
            if not decision.allowed:
                raise RateLimitExceeded(decision)
    except RateLimitExceeded as exc:
        decision = exc.decision
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": str(decision.remaining),
            },
        ) from exc
    except RateLimitUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Rate-limit protection is temporarily unavailable"
        ) from exc


async def _enforce_global_budget(
    request: Request,
    *,
    budget_name: str,
    limit: int,
) -> None:
    """Apply a fleet-wide request cap through the shared limiter adapter."""

    limiter: RateLimiter = getattr(request.app.state, "rate_limiter", None) or NoopRateLimiter()
    try:
        decision = await consume_global_budget(
            limiter,
            budget_name=budget_name,
            limit=limit,
        )
        if not decision.allowed:
            raise RateLimitExceeded(decision)
    except RateLimitExceeded as exc:
        decision = exc.decision
        raise HTTPException(
            status_code=429,
            detail="Service usage limit reached",
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": str(decision.remaining),
            },
        ) from exc
    except RateLimitUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Rate-limit protection is temporarily unavailable"
        ) from exc


async def require_ai_rate_limit(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> None:
    await _enforce_rate_limit(request, policy_name="ai", principal=principal)
    settings = getattr(request.app.state, "settings", None)
    await _enforce_global_budget(
        request,
        budget_name="ai-monthly",
        limit=int(getattr(settings, "ai_monthly_request_limit", 1000)),
    )


async def require_voice_rate_limit(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> None:
    await _enforce_rate_limit(request, policy_name="voice", principal=principal)
    settings = getattr(request.app.state, "settings", None)
    await _enforce_global_budget(
        request,
        budget_name="voice-monthly",
        limit=int(getattr(settings, "voice_monthly_request_limit", 250)),
    )


async def require_complaint_rate_limit(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> None:
    await _enforce_rate_limit(request, policy_name="complaint", principal=principal)


async def require_evidence_rate_limit(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> None:
    await _enforce_rate_limit(request, policy_name="evidence", principal=principal)


async def require_identity_rate_limit(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> None:
    await _enforce_rate_limit(request, policy_name="identity", principal=principal)


async def require_operator_rate_limit(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> None:
    await _enforce_rate_limit(request, policy_name="operator", principal=principal)


async def require_public_rate_limit(request: Request) -> None:
    await _enforce_rate_limit(request, policy_name="public", principal=None)


def get_db(request: Request) -> Generator[Session, None, None]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with session_factory() as session:
        yield session


def get_conversation_principal(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    """Apply the server-owned verification state to conversation handoffs."""

    try:
        return _principal_with_persisted_verification(principal, session)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity verification status is temporarily unavailable",
        ) from exc


def get_submission_service(
    request: Request, session: Session = Depends(get_db)
) -> ComplaintSubmissionService:
    verifier: EvidenceVerifier = getattr(
        request.app.state, "evidence_verifier", None
    ) or SqlAlchemyEvidenceVerifier(session)
    return ComplaintSubmissionService(
        SqlAlchemyComplaintSubmissionRepository(
            session, issue_cluster_policy=get_issue_cluster_policy(request)
        ),
        verifier,
        tracking_token_codec=getattr(request.app.state, "tracking_token_codec", None),
        routing_resolver=getattr(request.app.state, "routing_resolver", None),
        sla_policy=getattr(request.app.state, "sla_policy", None)
        or SyntheticSlaPolicy(),
    )


def get_issue_cluster_policy(request: Request) -> IssueClusterPolicy:
    settings = getattr(request.app.state, "settings", None)
    key = str(getattr(settings, "issue_cluster_hmac_key", ""))
    environment = str(getattr(settings, "environment", "development"))
    if not key:
        if environment not in {"development", "test"}:
            raise HTTPException(
                status_code=503, detail="Issue-cluster policy is not configured"
            )
        key = "local-development-only-issue-cluster-key-32-bytes"
    try:
        return IssueClusterPolicy(
            hmac_key=key,
            policy_version=str(
                getattr(settings, "issue_cluster_policy_version", "issue-cluster.v1")
            ),
            cell_precision=int(getattr(settings, "issue_cluster_cell_precision", 3)),
            window_hours=int(getattr(settings, "issue_cluster_window_hours", 72)),
            max_accuracy_m=float(
                getattr(settings, "issue_cluster_max_accuracy_m", 100.0)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Issue-cluster policy is not configured"
        ) from exc


def get_complaint_tracking_service(
    session: Session = Depends(get_db),
) -> ComplaintTrackingService:
    return ComplaintTrackingService(SqlAlchemyComplaintSubmissionRepository(session))


def get_disclosure_consent_service(
    request: Request, session: Session = Depends(get_db)
) -> DisclosureConsentService:
    settings = getattr(request.app.state, "settings", None)
    return DisclosureConsentService(
        SqlAlchemyComplaintSubmissionRepository(session),
        public_disclosure_enabled=bool(
            getattr(settings, "public_disclosure_enabled", False)
        ),
        policy_version=str(
            getattr(settings, "public_disclosure_policy_version", "disclosure-policy.v1")
        ),
    )


def get_public_complaint_tracking_service(
    request: Request, session: Session = Depends(get_db)
) -> PublicComplaintTrackingService:
    codec = getattr(request.app.state, "tracking_token_codec", None)
    if codec is None:
        raise HTTPException(status_code=503, detail="Public tracking is not configured")
    return PublicComplaintTrackingService(
        SqlAlchemyComplaintSubmissionRepository(session), codec
    )


def require_public_transparency_enabled(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None)
    if not bool(getattr(settings, "public_transparency_enabled", False)):
        raise HTTPException(status_code=404, detail="Public transparency is not enabled")


def get_public_transparency_service(
    request: Request,
    _enabled: None = Depends(require_public_transparency_enabled),
    session: Session = Depends(get_db),
) -> PublicTransparencyService:
    del _enabled
    settings = getattr(request.app.state, "settings", None)
    return PublicTransparencyService(
        SqlAlchemyComplaintSubmissionRepository(session),
        policy_version=str(
            getattr(settings, "public_transparency_policy_version", "")
        ),
    )


def get_complaint_transition_service(
    session: Session = Depends(get_db),
) -> ComplaintTransitionService:
    return ComplaintTransitionService(
        SqlAlchemyComplaintSubmissionRepository(session),
        closure_proof_repository=SqlAlchemyClosureProofRepository(session),
    )


def get_evidence_upload_service(
    request: Request, session: Session = Depends(get_db)
) -> EvidenceUploadService:
    settings = getattr(request.app.state, "settings", None)
    return EvidenceUploadService(
        SqlAlchemyEvidenceMetadataRepository(session),
        getattr(request.app.state, "capture_verifier", None)
        or UnconfiguredCaptureAttestationVerifier(),
        getattr(request.app.state, "object_store", None) or UnconfiguredObjectStore(),
        getattr(request.app.state, "media_inspector", None) or UnconfiguredMediaInspector(),
        browser_capture_review_required=bool(
            getattr(settings, "web_capture_review_required", True)
        ),
    )


def get_evidence_review_service(
    request: Request, session: Session = Depends(get_db)
) -> EvidenceReviewService:
    return EvidenceReviewService(
        SqlAlchemyEvidenceMetadataRepository(session),
        getattr(request.app.state, "object_store", None) or UnconfiguredObjectStore(),
    )


def get_complaint_draft_service(request: Request) -> ComplaintDraftService:
    orchestrator: AgentOrchestrator | None = getattr(
        request.app.state, "ai_orchestrator", None
    )
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Complaint extraction is not configured")
    return ComplaintDraftService(orchestrator)


def get_voice_draft_service(
    request: Request, session: Session = Depends(get_db)
) -> VoiceDraftService:
    orchestrator: AgentOrchestrator | None = getattr(
        request.app.state, "ai_orchestrator", None
    )
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Complaint extraction is not configured")
    return VoiceDraftService(
        SqlAlchemyEvidenceMetadataRepository(session),
        SqlAlchemyVoiceDraftRequestRepository(session),
        getattr(request.app.state, "speech_to_text", None) or UnconfiguredSpeechToText(),
        ComplaintDraftService(orchestrator),
    )


def get_identity_verification_status_service(
    request: Request, session: Session = Depends(get_db),
) -> IdentityVerificationStatusService:
    settings = getattr(request.app.state, "settings", None)
    return IdentityVerificationStatusService(
        SqlAlchemyIdentityVerificationRepository(session),
        provider=str(getattr(settings, "identity_provider", "digilocker")),  # type: ignore[arg-type]
    )


def get_admin_complaint_query_service(
    session: Session = Depends(get_db),
) -> AdminComplaintQueryService:
    return AdminComplaintQueryService(SqlAlchemyComplaintSubmissionRepository(session))


def get_conversation_service(
    request: Request, session: Session = Depends(get_db)
) -> ConversationService:
    orchestrator: AgentOrchestrator | None = getattr(
        request.app.state, "ai_orchestrator", None
    )
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Conversation service is not configured")
    return ConversationService(
        orchestrator,
        SqlAlchemyConversationSessionRepository(session),
        ComplaintDraftService(orchestrator),
        SchemeKnowledgeService(SqlAlchemySchemeKnowledgeRepository(session)),
        tone_governor=getattr(request.app.state, "tone_governor", None),
    )


def get_scheme_knowledge_service(
    session: Session = Depends(get_db),
) -> SchemeKnowledgeService:
    return SchemeKnowledgeService(SqlAlchemySchemeKnowledgeRepository(session))


def get_scheme_review_service(session: Session = Depends(get_db)) -> SchemeReviewService:
    return SchemeReviewService(SqlAlchemySchemeKnowledgeRepository(session))


def get_content_reviewer_principal(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> AuthenticatedPrincipal:
    if not has_capability(principal, "scheme.review"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A content-review capability is required",
        )
    return principal


def get_workflow_signal_service(
    request: Request, session: Session = Depends(get_db)
) -> WorkflowSignalService:
    sender = getattr(request.app.state, "workflow_signal_sender", None)
    if sender is None:
        raise HTTPException(status_code=503, detail="Workflow signaling is not configured")
    return WorkflowSignalService(
        SqlAlchemyWorkflowSignalRepository(session),
        sender,
        proof_verifier=getattr(request.app.state, "closure_proof_verifier", None)
        or UnconfiguredClosureProofVerifier(),
        proof_repository=SqlAlchemyClosureProofRepository(session),
        reply_repository=SqlAlchemyDepartmentReplyRepository(session),
        resolution_repository=SqlAlchemyCitizenResolutionRepository(session),
    )


def get_routing_activation_service(
    request: Request, session: Session = Depends(get_db)
) -> RoutingActivationService:
    resolver = getattr(request.app.state, "routing_activation_resolver", None)
    if resolver is None:
        raise HTTPException(status_code=503, detail="Routing activation is not configured")
    return RoutingActivationService(
        SqlAlchemyComplaintSubmissionRepository(session), resolver
    )
