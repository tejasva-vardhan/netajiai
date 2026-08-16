"""FastAPI entrypoint for the greenfield backend slice."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import re
from time import monotonic
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    get_complaint_draft_service,
    get_voice_draft_service,
    require_ai_rate_limit,
    require_voice_rate_limit,
    require_complaint_rate_limit,
    require_evidence_rate_limit,
    require_identity_rate_limit,
    require_operator_rate_limit,
    require_public_rate_limit,
    get_complaint_transition_service,
    get_complaint_tracking_service,
    get_disclosure_consent_service,
    get_conversation_service,
    get_conversation_principal,
    get_current_principal,
    get_admin_complaint_query_service,
    get_operator_principal,
    get_verified_principal,
    get_db,
    get_evidence_upload_service,
    get_evidence_review_service,
    get_identity_verification_status_service,
    require_identity_status_rate_limit,
    get_public_complaint_tracking_service,
    get_public_transparency_service,
    get_submission_service,
    get_workflow_signal_service,
    get_routing_activation_service,
    get_scheme_knowledge_service,
    get_scheme_review_service,
    get_content_reviewer_principal,
)
from backend.app.application.drafts import ComplaintDraftService, DraftRejected, DraftUnavailable
from backend.app.application.voice_drafts import (
    SpeechToTextUnavailable,
    VoiceDraftIdempotencyConflict,
    VoiceDraftRejected,
    VoiceDraftService,
)
from backend.app.application.evidence_review import (
    EvidenceReviewConflict,
    EvidenceReviewCursorInvalid,
    EvidenceReviewService,
)
from backend.app.application.rate_limits import InMemoryRateLimiter, NoopRateLimiter
from backend.app.application.closure import (
    ClosureProofConflict,
    ClosureProofRejected,
    ClosureProofRequired,
    ClosureProofUnavailable,
)
from backend.app.application.admin import AdminComplaintQueryService, AdminCursorInvalid
from backend.app.application.transparency import PublicTransparencyService
from backend.app.application.conversation import (
    ConversationIdempotencyConflict,
    ConversationService,
    ConversationSessionOwnershipError,
    ConversationUnavailable,
)
from backend.app.application.workflow_signals import (
    CitizenResolutionConflict,
    CitizenResolutionUnavailable,
    CitizenConfirmationNotDue,
    WorkflowSignalConflict,
    WorkflowSignalNotAuthorized,
    WorkflowSignalService,
    WorkflowSignalUnavailable,
)
from backend.app.application.department_replies import DepartmentReplyConflict
from backend.app.application.routing_activation import (
    RoutingActivationConflict,
    RoutingActivationNotAuthorized,
    RoutingActivationService,
    RoutingActivationUnavailable,
)
from backend.app.application.schemes import (
    SchemeKnowledgeService,
    SchemeKnowledgeUnavailable,
    SchemeReviewConflict,
    SchemeReviewCursorInvalid,
    SchemeReviewRejected,
    SchemeReviewService,
)
from backend.app.application.complaints import (
    ComplaintNotFound,
    ComplaintSubmissionConflict,
    TransitionIdempotencyConflict,
    ComplaintSubmissionService,
    ComplaintTransitionService,
    ComplaintTrackingService,
    PublicComplaintTrackingService,
    EvidenceVerificationUnavailable,
    SubmissionRejected,
    TransitionNotAuthorized,
)
from backend.app.application.routing import RoutingResolverUnavailable
from backend.app.application.sla import SlaPolicyUnavailable
from backend.app.application.routing import RoutingState
from backend.app.application.evidence import (
    EvidenceAssetNotFound,
    EvidenceCaptureRejected,
    EvidenceProviderUnavailable,
    EvidenceIdempotencyConflict,
    EvidenceUploadService,
)
from backend.app.application.identity import (
    IdentityAuthorizationRejected,
    IdentityAuthorizationService,
    IdentityVerificationStatusService,
)
from backend.app.application.disclosure import (
    DisclosureConsentConflict,
    DisclosurePolicyUnavailable,
    DisclosureConsentService,
)
from backend.app.config import ProductionConfigurationError, Settings
from backend.app.contracts.complaints import (
    ComplaintTrackingResponse,
    CreateComplaintRequest,
    ComplaintResponse,
    AdminComplaintPage,
    DisclosureConsentRequest,
    DisclosureConsentResponse,
    PublicComplaintTrackingResponse,
    TransitionComplaintRequest,
)
from backend.app.contracts.admin import AdminOverviewResponse
from backend.app.contracts.catalog import ComplaintCategory, ComplaintCategoryCatalog
from backend.app.contracts.conversation import ConversationTurnRequest, ConversationTurnResponse
from backend.app.contracts.ai import (
    ComplaintDraftRequest,
    ComplaintExtraction,
    VoiceDraftRequest,
    VoiceDraftResponse,
)
from backend.app.contracts.evidence import (
    CaptureSessionRequest,
    CaptureSessionResponse,
    CompleteEvidencePartRequest,
    CreateEvidenceUploadRequest,
    EvidenceCompletionResponse,
    EvidencePartCompletionResponse,
    EvidenceUploadResponse,
)
from backend.app.contracts.evidence_review import (
    EvidenceReviewDecisionRequest,
    EvidenceReviewDecisionResponse,
    EvidenceReviewPage,
)
from backend.app.contracts.http import HealthResponse, ReadinessResponse
from backend.app.contracts.transparency import PublicTransparencyResponse
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.contracts.identity import (
    IdentityAuthorizationCallbackResponse,
    IdentityAuthorizationStartResponse,
    IdentityVerificationStatusResponse,
)
from backend.app.contracts.workflow_signals import (
    CitizenConfirmationSignalRequest,
    DepartmentResponseSignalRequest,
    RoutingActivationSignalRequest,
    WorkflowSignalResponse,
)
from backend.app.contracts.schemes import (
    SchemeAnswerRequest,
    SchemeAnswerResponse,
    SchemeIngestionRequest,
    SchemeIngestionResponse,
    SchemeApprovalResponse,
    SchemeReviewPage,
)
from backend.app.domain.complaints import ComplaintStatus, InvalidTransition
from backend.app.domain.issue_catalog import ISSUE_CATALOG_VERSION, get_issue_categories
from backend.app.infrastructure.browser_capture import BrowserCaptureSessionSigner
from backend.app.observability import Telemetry
from backend.app.infrastructure.tracking import HmacPublicTrackingTokenCodec
from backend.app.infrastructure.digilocker import TemporaryLocalIdentityTransport


logger = logging.getLogger("aineta.api")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


def _request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    return candidate if _REQUEST_ID.fullmatch(candidate) else str(uuid4())


def _route_template(request: Request) -> str:
    """Return only the registered route pattern, never path/query values."""

    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else "unmatched"


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: Callable[[], Any] | None = None,
    principal_resolver: Callable[[str], AuthenticatedPrincipal] | None = None,
    evidence_verifier: Any | None = None,
    capture_verifier: Any | None = None,
    capture_session_issuer: Any | None = None,
    object_store: Any | None = None,
    media_inspector: Any | None = None,
    identity_authorization_service_factory: Callable[
        [Session], IdentityAuthorizationService
    ]
    | None = None,
    tracking_token_codec: Any | None = None,
    ai_orchestrator: Any | None = None,
    tone_governor: Any | None = None,
    routing_resolver: Any | None = None,
    sla_policy: Any | None = None,
    routing_activation_resolver: Any | None = None,
    workflow_signal_sender: Any | None = None,
    closure_proof_verifier: Any | None = None,
    speech_to_text: Any | None = None,
    rate_limiter: Any | None = None,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    config.validate_for_production()
    if (
        config.environment in {"development", "test"}
        and capture_session_issuer is None
        and config.web_capture_session_hmac_key
    ):
        local_browser_signer = BrowserCaptureSessionSigner(
            config.web_capture_session_hmac_key,
            ttl_seconds=config.web_capture_session_ttl_seconds,
        )
        capture_session_issuer = local_browser_signer
        if capture_verifier is None:
            capture_verifier = local_browser_signer
    telemetry = telemetry or Telemetry.from_settings(config)
    if config.environment == "production" and not telemetry.enabled:
        raise ProductionConfigurationError(
            "An enabled OpenTelemetry telemetry adapter is required for production"
        )
    if config.environment in {"staging", "production"} and rate_limiter is None:
        raise ProductionConfigurationError(
            "A shared rate_limiter adapter is required for staging and production"
        )
    if config.environment in {"staging", "production"} and sla_policy is None:
        raise ProductionConfigurationError(
            "A versioned sla_policy adapter is required for staging and production"
        )
    if config.environment in {"staging", "production"} and isinstance(
        rate_limiter, (NoopRateLimiter, InMemoryRateLimiter)
    ):
        raise ProductionConfigurationError(
            "A shared rate_limiter adapter is required for staging and production"
        )
    if tracking_token_codec is None and config.public_tracking_token_secret:
        tracking_token_codec = HmacPublicTrackingTokenCodec(
            config.public_tracking_token_secret
        )
    if config.environment in {"staging", "production"}:
        missing_adapters = [
            name
            for name, value in {
                "session_factory": session_factory,
                "principal_resolver": principal_resolver,
                "capture_verifier": capture_verifier,
                "object_store": object_store,
                "media_inspector": media_inspector,
                "identity_authorization_service_factory": identity_authorization_service_factory,
                "ai_orchestrator": ai_orchestrator,
                "routing_resolver": routing_resolver,
                "sla_policy": sla_policy,
                "routing_activation_resolver": routing_activation_resolver,
                "workflow_signal_sender": workflow_signal_sender,
                "closure_proof_verifier": closure_proof_verifier,
                "speech_to_text": speech_to_text,
                "rate_limiter": rate_limiter,
            }.items()
            if value is None
        ]
        if config.web_capture_enabled and capture_session_issuer is None:
            missing_adapters.append("capture_session_issuer")
        if missing_adapters:
            raise ProductionConfigurationError(
                "Missing required staging/production adapters: "
                + ", ".join(missing_adapters)
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            telemetry.shutdown()

    app = FastAPI(
        title="AI Neta API",
        version="0.1.0",
        description="Production-oriented civic grievance API boundary.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.api_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
            "X-Device-ID",
        ],
        expose_headers=[
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-Request-ID",
        ],
    )

    @app.middleware("http")
    async def request_correlation_middleware(request: Request, call_next: Any) -> Any:
        correlation_id = _request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = correlation_id
        started = monotonic()
        with telemetry.tracer.start_as_current_span(
            f"HTTP {request.method}"
        ) as span:
            span.set_attribute("http.request.method", request.method)
            try:
                response = await call_next(request)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
                logger.error(
                    "http_request_failed",
                    extra={
                        "request_id": correlation_id,
                        "method": request.method,
                        "route": _route_template(request),
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            route = _route_template(request)
            span.set_attribute("http.route", route)
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
        response.headers["X-Request-ID"] = correlation_id
        telemetry.record_http_request(
            method=request.method,
            route=_route_template(request),
            status_code=response.status_code,
            duration_seconds=monotonic() - started,
        )
        logger.info(
            "http_request_completed",
            extra={
                "request_id": correlation_id,
                "method": request.method,
                "route": _route_template(request),
                "status_code": response.status_code,
                "duration_ms": round((monotonic() - started) * 1000, 2),
            },
        )
        return response
    app.state.session_factory = session_factory
    app.state.settings = config
    app.state.principal_resolver = principal_resolver
    app.state.evidence_verifier = evidence_verifier
    app.state.capture_verifier = capture_verifier
    app.state.capture_session_issuer = capture_session_issuer
    app.state.object_store = object_store
    app.state.media_inspector = media_inspector
    app.state.identity_authorization_service_factory = identity_authorization_service_factory
    app.state.tracking_token_codec = tracking_token_codec
    app.state.ai_orchestrator = ai_orchestrator
    app.state.tone_governor = tone_governor
    app.state.routing_resolver = routing_resolver
    app.state.sla_policy = sla_policy
    app.state.routing_activation_resolver = routing_activation_resolver
    app.state.workflow_signal_sender = workflow_signal_sender
    app.state.closure_proof_verifier = closure_proof_verifier
    app.state.speech_to_text = speech_to_text
    app.state.rate_limiter = rate_limiter
    app.state.telemetry = telemetry

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok", service=config.service_name, environment=config.environment, version="0.1.0"
        )

    @app.get("/favicon.ico", include_in_schema=False, status_code=status.HTTP_204_NO_CONTENT)
    def favicon() -> Response:
        """Keep browser-opened provider callbacks free of a spurious 404."""

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/ready", response_model=ReadinessResponse, tags=["operations"])
    def ready(request: Request) -> ReadinessResponse:
        """Report readiness only after a bounded database connectivity check."""

        ready_session_factory = getattr(request.app.state, "session_factory", None)
        if ready_session_factory is None:
            raise HTTPException(status_code=503, detail="Database is not ready")
        try:
            with ready_session_factory() as session:
                session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning(
                "readiness_database_check_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise HTTPException(status_code=503, detail="Database is not ready") from exc
        return ReadinessResponse(
            status="ready",
            service=config.service_name,
            environment=config.environment,
            version="0.1.0",
            checks={"database": "ok"},
        )

    @app.post(
        "/api/v1/complaints/draft",
        response_model=ComplaintExtraction,
        tags=["complaints"],
    )
    def draft_complaint(
        payload: ComplaintDraftRequest,
        _rate_limit: None = Depends(require_ai_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_verified_principal),
        service: ComplaintDraftService = Depends(get_complaint_draft_service),
    ) -> ComplaintExtraction:
        """Extract a draft; the result is never a lifecycle or routing command."""

        try:
            return service.extract(principal, payload)
        except DraftRejected as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except DraftUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Complaint drafting is temporarily unavailable"
            ) from exc

    @app.get(
        "/api/v1/complaints/categories",
        response_model=ComplaintCategoryCatalog,
        tags=["complaints"],
    )
    async def list_complaint_categories(
        _rate_limit: None = Depends(require_public_rate_limit),
    ) -> ComplaintCategoryCatalog:
        """Return the server-owned tap/voice intake taxonomy."""

        return ComplaintCategoryCatalog(
            version=ISSUE_CATALOG_VERSION,
            items=[
                ComplaintCategory(
                    code=category.code,
                    icon=category.icon,
                    label_hi=category.label_hi,
                    label_en=category.label_en,
                    spoken_hi=category.spoken_hi,
                )
                for category in get_issue_categories()
            ],
        )

    @app.post(
        "/api/v1/complaints/voice-draft",
        response_model=VoiceDraftResponse,
        tags=["complaints"],
    )
    def draft_voice_complaint(
        payload: VoiceDraftRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_voice_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_verified_principal),
        service: VoiceDraftService = Depends(get_voice_draft_service),
    ) -> VoiceDraftResponse:
        """Transcribe verified audio and run the bounded draft extractor."""

        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            return service.extract(
                principal,
                audio_asset_id=payload.audio_asset_id,
                language=payload.language,
                idempotency_key=idempotency_key,
                now=datetime.now(timezone.utc),
            )
        except VoiceDraftIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except VoiceDraftRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SpeechToTextUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Speech transcription is temporarily unavailable"
            ) from exc
        except DraftUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Complaint drafting is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/conversations/turn",
        response_model=ConversationTurnResponse,
        tags=["conversation"],
    )
    def conversation_turn(
        payload: ConversationTurnRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_ai_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_conversation_principal),
        service: ConversationService = Depends(get_conversation_service),
    ) -> ConversationTurnResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            return service.turn(
                principal,
                text=payload.text,
                language=payload.language,
                session_id=payload.session_id,
                idempotency_key=idempotency_key or "",
                now=datetime.now(timezone.utc),
            )
        except ConversationSessionOwnershipError as exc:
            raise HTTPException(status_code=404, detail="Conversation session was not found") from exc
        except ConversationIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ConversationUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Conversation service is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/schemes/answer",
        response_model=SchemeAnswerResponse,
        tags=["schemes"],
    )
    def answer_scheme_question(
        payload: SchemeAnswerRequest,
        _rate_limit: None = Depends(require_ai_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
        service: SchemeKnowledgeService = Depends(get_scheme_knowledge_service),
    ) -> SchemeAnswerResponse:
        del principal
        try:
            return service.answer(
                query=payload.query,
                language=payload.language,
                jurisdiction_code=payload.jurisdiction_code,
                now=datetime.now(timezone.utc),
            )
        except SchemeKnowledgeUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Verified scheme information is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/admin/schemes",
        response_model=SchemeIngestionResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["admin-schemes"],
    )
    def stage_scheme_record(
        payload: SchemeIngestionRequest,
        _rate_limit: None = Depends(require_operator_rate_limit),
        _principal: AuthenticatedPrincipal = Depends(get_operator_principal),
        service: SchemeReviewService = Depends(get_scheme_review_service),
    ) -> SchemeIngestionResponse:
        try:
            scheme_id = service.stage(payload, now=datetime.now(timezone.utc))
        except SchemeReviewRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SchemeKnowledgeUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Scheme review is temporarily unavailable"
            ) from exc
        return SchemeIngestionResponse(scheme_id=scheme_id, status="pending_review")

    @app.get(
        "/api/v1/admin/schemes/review-queue",
        response_model=SchemeReviewPage,
        tags=["admin-schemes"],
    )
    def list_scheme_review_queue(
        limit: int = Query(default=25, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=512),
        _rate_limit: None = Depends(require_operator_rate_limit),
        _principal: AuthenticatedPrincipal = Depends(get_content_reviewer_principal),
        service: SchemeReviewService = Depends(get_scheme_review_service),
    ) -> SchemeReviewPage:
        try:
            return service.list_pending(limit=limit, cursor=cursor)
        except SchemeReviewCursorInvalid as exc:
            raise HTTPException(status_code=400, detail="Invalid scheme review cursor") from exc
        except SchemeKnowledgeUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Scheme review is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/admin/schemes/{scheme_id}/approve",
        response_model=SchemeApprovalResponse,
        tags=["admin-schemes"],
    )
    def approve_scheme_record(
        scheme_id: UUID = Path(),
        _rate_limit: None = Depends(require_operator_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_content_reviewer_principal),
        service: SchemeReviewService = Depends(get_scheme_review_service),
    ) -> SchemeApprovalResponse:
        try:
            return service.approve(
                scheme_id,
                reviewer_id=principal.subject_ref,
                now=datetime.now(timezone.utc),
            )
        except SchemeReviewRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SchemeReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SchemeKnowledgeUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Scheme review is temporarily unavailable"
            ) from exc

    @app.get(
        "/api/v1/public/complaints/{tracking_token}",
        response_model=PublicComplaintTrackingResponse,
        tags=["public-tracking"],
    )
    def get_public_complaint(
        tracking_token: str = Path(min_length=1, max_length=100),
        _rate_limit: None = Depends(require_public_rate_limit),
        service: PublicComplaintTrackingService = Depends(
            get_public_complaint_tracking_service
        ),
    ) -> PublicComplaintTrackingResponse:
        try:
            return service.get(tracking_token)
        except ComplaintNotFound as exc:
            raise HTTPException(status_code=404, detail="Complaint was not found") from exc

    @app.get(
        "/api/v1/public/transparency",
        response_model=PublicTransparencyResponse,
        tags=["public-transparency"],
    )
    def get_public_transparency(
        _rate_limit: None = Depends(require_public_rate_limit),
        service: PublicTransparencyService = Depends(get_public_transparency_service),
    ) -> PublicTransparencyResponse:
        return service.get(now=datetime.now(timezone.utc))

    @app.get(
        "/api/v1/admin/complaints",
        response_model=AdminComplaintPage,
        tags=["admin"],
    )
    def list_admin_complaints(
        status_filter: ComplaintStatus | None = Query(default=None, alias="status"),
        execution_zone_state: RoutingState | None = Query(default=None),
        limit: int = Query(default=25, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=512),
        _rate_limit: None = Depends(require_operator_rate_limit),
        _principal: AuthenticatedPrincipal = Depends(get_operator_principal),
        service: AdminComplaintQueryService = Depends(get_admin_complaint_query_service),
    ) -> AdminComplaintPage:
        try:
            return service.list(
                status=status_filter,
                execution_zone_state=execution_zone_state,
                limit=limit,
                cursor=cursor,
            )
        except AdminCursorInvalid as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc

    @app.get(
        "/api/v1/admin/overview",
        response_model=AdminOverviewResponse,
        tags=["admin"],
    )
    def get_admin_overview(
        _rate_limit: None = Depends(require_operator_rate_limit),
        _principal: AuthenticatedPrincipal = Depends(get_operator_principal),
        service: AdminComplaintQueryService = Depends(get_admin_complaint_query_service),
    ) -> AdminOverviewResponse:
        """Return redacted aggregate facts for the operator control tower."""

        return service.overview()

    @app.get(
        "/api/v1/admin/evidence/review-queue",
        response_model=EvidenceReviewPage,
        tags=["admin-evidence"],
    )
    def list_evidence_review_queue(
        limit: int = Query(default=25, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=512),
        _rate_limit: None = Depends(require_operator_rate_limit),
        _principal: AuthenticatedPrincipal = Depends(get_operator_principal),
        service: EvidenceReviewService = Depends(get_evidence_review_service),
    ) -> EvidenceReviewPage:
        try:
            return service.list(limit=limit, cursor=cursor)
        except EvidenceReviewCursorInvalid as exc:
            raise HTTPException(status_code=400, detail="Invalid evidence review cursor") from exc
        except EvidenceProviderUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Evidence review service is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/admin/evidence/{evidence_asset_id}/review",
        response_model=EvidenceReviewDecisionResponse,
        tags=["admin-evidence"],
    )
    def decide_evidence_review(
        payload: EvidenceReviewDecisionRequest,
        evidence_asset_id: str = Path(min_length=1),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_operator_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_operator_principal),
        service: EvidenceReviewService = Depends(get_evidence_review_service),
    ) -> EvidenceReviewDecisionResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            evidence_uuid = UUID(evidence_asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid evidence asset ID") from exc
        try:
            return service.decide(
                principal,
                evidence_asset_id=evidence_uuid,
                decision=payload.decision,
                reason_code=payload.reason_code,
                idempotency_key=idempotency_key,
                now=datetime.now(timezone.utc),
            )
        except EvidenceReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/v1/admin/complaints/{complaint_id}/routing-activation",
        response_model=WorkflowSignalResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["admin"],
    )
    async def activate_complaint_routing(
        _payload: RoutingActivationSignalRequest,
        request: Request,
        complaint_id: str = Path(min_length=1),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_operator_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_operator_principal),
        routing_service: RoutingActivationService = Depends(
            get_routing_activation_service
        ),
        signal_service: WorkflowSignalService = Depends(get_workflow_signal_service),
    ) -> WorkflowSignalResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            complaint_uuid = UUID(complaint_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid complaint ID") from exc
        correlation_id = getattr(request.state, "request_id", str(uuid4()))
        try:
            routing_service.activate(
                principal,
                complaint_uuid,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
            return await signal_service.routing_activation(
                principal,
                complaint_id=complaint_uuid,
                idempotency_key=idempotency_key,
                now=datetime.now(timezone.utc),
            )
        except RoutingActivationNotAuthorized as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RoutingActivationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RoutingActivationUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Routing activation is temporarily unavailable"
            ) from exc
        except WorkflowSignalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkflowSignalUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Complaint workflow is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/admin/complaints/{complaint_id}/department-response",
        response_model=WorkflowSignalResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["admin"],
    )
    async def signal_department_response(
        payload: DepartmentResponseSignalRequest,
        complaint_id: str = Path(min_length=1),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_operator_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_operator_principal),
        service: WorkflowSignalService = Depends(get_workflow_signal_service),
    ) -> WorkflowSignalResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            complaint_uuid = UUID(complaint_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid complaint ID") from exc
        try:
            return await service.department_response(
                principal,
                complaint_id=complaint_uuid,
                outcome=payload.outcome,
                reply_text=payload.reply_text,
                proof_type=payload.proof.proof_type if payload.proof else None,
                proof_reference=payload.proof.proof_reference if payload.proof else None,
                idempotency_key=idempotency_key,
                now=datetime.now(timezone.utc),
            )
        except ClosureProofRequired as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ClosureProofRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ClosureProofConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ClosureProofUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Closure proof verification is temporarily unavailable"
            ) from exc
        except DepartmentReplyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkflowSignalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkflowSignalNotAuthorized as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except WorkflowSignalUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Complaint workflow is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/complaints/{complaint_id}/citizen-confirmation",
        response_model=WorkflowSignalResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["complaints"],
    )
    async def signal_citizen_confirmation(
        payload: CitizenConfirmationSignalRequest,
        complaint_id: str = Path(min_length=1),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_complaint_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
        service: WorkflowSignalService = Depends(get_workflow_signal_service),
        tracking: ComplaintTrackingService = Depends(get_complaint_tracking_service),
    ) -> WorkflowSignalResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            complaint_uuid = UUID(complaint_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid complaint ID") from exc
        try:
            return await service.citizen_confirmation(
                principal,
                complaint_id=complaint_uuid,
                outcome=payload.outcome,
                idempotency_key=idempotency_key,
                tracking=tracking,
                now=datetime.now(timezone.utc),
            )
        except ComplaintNotFound as exc:
            raise HTTPException(status_code=404, detail="Complaint was not found") from exc
        except CitizenConfirmationNotDue as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CitizenResolutionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CitizenResolutionUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Citizen outcome service is temporarily unavailable"
            ) from exc
        except WorkflowSignalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkflowSignalUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Complaint workflow is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/identity/digilocker/start",
        response_model=IdentityAuthorizationStartResponse,
        tags=["identity"],
    )
    def start_digilocker_authorization(
        request: Request,
        session: Session = Depends(get_db),
        _rate_limit: None = Depends(require_identity_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
    ) -> IdentityAuthorizationStartResponse:
        factory: Callable[[Session], IdentityAuthorizationService] | None = getattr(
            request.app.state, "identity_authorization_service_factory", None
        )
        if factory is None:
            raise HTTPException(status_code=503, detail="Identity verification is not configured")
        service = factory(session)
        try:
            authorization_url, expires_at = service.start(principal)
        except IdentityAuthorizationRejected as exc:
            raise HTTPException(status_code=401, detail="Authenticated identity is required") from exc
        return IdentityAuthorizationStartResponse(
            authorization_url=authorization_url,
            expires_at=expires_at,
        )

    @app.get(
        "/api/v1/identity/digilocker/callback",
        response_model=IdentityAuthorizationCallbackResponse,
        tags=["identity"],
    )
    def complete_digilocker_authorization(
        request: Request,
        session: Session = Depends(get_db),
        _rate_limit: None = Depends(require_public_rate_limit),
        state: str | None = Query(default=None, max_length=512),
        code: str | None = Query(default=None, max_length=4_000),
        error: str | None = Query(default=None, max_length=255),
    ) -> IdentityAuthorizationCallbackResponse:
        factory: Callable[[Session], IdentityAuthorizationService] | None = getattr(
            request.app.state, "identity_authorization_service_factory", None
        )
        if factory is None:
            raise HTTPException(status_code=503, detail="Identity verification is not configured")
        service = factory(session)
        try:
            record = service.complete(state=state or "", code=code, error=error)
        except IdentityAuthorizationRejected as exc:
            raise HTTPException(status_code=400, detail="Invalid identity authorization response") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Identity provider verification failed") from exc
        return IdentityAuthorizationCallbackResponse(
            verification_id=str(record.verification_id),
            status=record.status,  # type: ignore[arg-type]
        )

    @app.get("/api/v1/identity/temporary/authorize", include_in_schema=False)
    def authorize_temporary_identity(
        state: str = Query(min_length=1, max_length=512),
    ) -> RedirectResponse:
        """Complete the local interim identity handoff without claiming DigiLocker."""

        if config.environment not in {"development", "test"} or config.identity_provider != "temporary":
            raise HTTPException(status_code=404, detail="Temporary identity is disabled")
        transport = TemporaryLocalIdentityTransport(config.identity_state_encryption_key)
        code = transport.issue_code(state)
        callback = config.digilocker_redirect_uri
        separator = "&" if "?" in callback else "?"
        return RedirectResponse(
            url=f"{callback}{separator}{urlencode({'state': state, 'code': code})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.get(
        "/api/v1/identity/digilocker/status",
        response_model=IdentityVerificationStatusResponse,
        tags=["identity"],
    )
    def get_digilocker_status(
        _rate_limit: None = Depends(require_identity_status_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
        service: IdentityVerificationStatusService = Depends(
            get_identity_verification_status_service
        ),
    ) -> IdentityVerificationStatusResponse:
        try:
            return service.get(principal)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Identity verification status is temporarily unavailable",
            ) from exc

    @app.post(
        "/api/v1/complaints",
        response_model=ComplaintResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["complaints"],
    )
    def create_complaint(
        payload: CreateComplaintRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_complaint_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_verified_principal),
        service: ComplaintSubmissionService = Depends(get_submission_service),
    ) -> ComplaintResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        correlation_id = getattr(request.state, "request_id", str(uuid4()))
        try:
            return service.create(
                principal,
                payload,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        except ComplaintSubmissionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SubmissionRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EvidenceVerificationUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Evidence verification is temporarily unavailable"
            ) from exc
        except RoutingResolverUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Routing is temporarily unavailable"
            ) from exc
        except SlaPolicyUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="SLA policy is temporarily unavailable"
            ) from exc
        except IntegrityError as exc:
            # A concurrent request with the same citizen/key is not a second
            # submission. The caller may safely retry with the same key.
            raise HTTPException(
                status_code=409,
                detail="A complaint submission with this idempotency key is in progress",
            ) from exc

    @app.get(
        "/api/v1/complaints/{complaint_id}",
        response_model=ComplaintTrackingResponse,
        tags=["complaints"],
    )
    def get_complaint(
        complaint_id: str = Path(min_length=1),
        _rate_limit: None = Depends(require_complaint_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
        service: ComplaintTrackingService = Depends(get_complaint_tracking_service),
    ) -> ComplaintTrackingResponse:
        try:
            complaint_uuid = UUID(complaint_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid complaint ID") from exc
        try:
            return service.get(principal, complaint_uuid)
        except ComplaintNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/api/v1/complaints/{complaint_id}/disclosure-consent",
        response_model=DisclosureConsentResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["complaints"],
    )
    def record_disclosure_consent(
        payload: DisclosureConsentRequest,
        request: Request,
        complaint_id: UUID = Path(),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_complaint_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
        service: DisclosureConsentService = Depends(get_disclosure_consent_service),
    ) -> DisclosureConsentResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            return service.record(
                principal,
                complaint_id,
                payload,
                idempotency_key=idempotency_key,
                correlation_id=getattr(request.state, "request_id", str(uuid4())),
            )
        except ComplaintNotFound as exc:
            raise HTTPException(status_code=404, detail="Complaint was not found") from exc
        except DisclosureConsentConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except DisclosurePolicyUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/api/v1/complaints/{complaint_id}/transitions",
        response_model=ComplaintTrackingResponse,
        tags=["complaints"],
    )
    def transition_complaint(
        payload: TransitionComplaintRequest,
        request: Request,
        complaint_id: str = Path(min_length=1),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_operator_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
        service: ComplaintTransitionService = Depends(get_complaint_transition_service),
    ) -> ComplaintTrackingResponse:
        try:
            complaint_uuid = UUID(complaint_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid complaint ID") from exc
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            return service.transition(
                principal,
                complaint_uuid,
                payload.to_status,
                idempotency_key=idempotency_key,
                correlation_id=getattr(request.state, "request_id", str(uuid4())),
            )
        except TransitionNotAuthorized as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ComplaintNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TransitionIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Transition is being retried") from exc

    @app.post(
        "/api/v1/evidence/capture-sessions",
        response_model=CaptureSessionResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["evidence"],
    )
    def create_capture_session(
        payload: CaptureSessionRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_evidence_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_verified_principal),
    ) -> CaptureSessionResponse:
        if not config.web_capture_enabled:
            raise HTTPException(status_code=404, detail="Web capture is not enabled")
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        issuer = getattr(app.state, "capture_session_issuer", None)
        if issuer is None:
            raise HTTPException(status_code=503, detail="Web capture is not configured")
        try:
            session = issuer.issue(
                citizen_id=principal.subject_ref,
                asset_type=payload.asset_type,
                idempotency_key=idempotency_key,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Capture session could not be created") from exc
        return CaptureSessionResponse(
            capture_token=session.token,
            expires_at=session.expires_at,
        )

    @app.post(
        "/api/v1/evidence/uploads",
        response_model=EvidenceUploadResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["evidence"],
    )
    def create_evidence_upload(
        payload: CreateEvidenceUploadRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _rate_limit: None = Depends(require_evidence_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_verified_principal),
        service: EvidenceUploadService = Depends(get_evidence_upload_service),
    ) -> EvidenceUploadResponse:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="Idempotency-Key is required")
        try:
            return service.create_upload(
                principal, payload, idempotency_key=idempotency_key
            )
        except EvidenceIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EvidenceCaptureRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EvidenceProviderUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Evidence storage is temporarily unavailable"
            ) from exc
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Duplicate upload request") from exc

    @app.post(
        "/api/v1/evidence/{evidence_asset_id}/complete",
        response_model=EvidenceCompletionResponse,
        tags=["evidence"],
    )
    def complete_evidence_upload(
        evidence_asset_id: str = Path(min_length=1),
        _rate_limit: None = Depends(require_evidence_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_verified_principal),
        service: EvidenceUploadService = Depends(get_evidence_upload_service),
    ) -> EvidenceCompletionResponse:
        try:
            asset_id = UUID(evidence_asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid evidence asset ID") from exc
        try:
            return service.complete_upload(principal, asset_id)
        except EvidenceAssetNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except EvidenceCaptureRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EvidenceProviderUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Evidence storage is temporarily unavailable"
            ) from exc

    @app.post(
        "/api/v1/evidence/{evidence_asset_id}/parts/{part_number}",
        response_model=EvidencePartCompletionResponse,
        tags=["evidence"],
    )
    def complete_evidence_part(
        payload: CompleteEvidencePartRequest,
        evidence_asset_id: str = Path(min_length=1),
        part_number: int = Path(ge=1, le=10_000),
        _rate_limit: None = Depends(require_evidence_rate_limit),
        principal: AuthenticatedPrincipal = Depends(get_verified_principal),
        service: EvidenceUploadService = Depends(get_evidence_upload_service),
    ) -> EvidencePartCompletionResponse:
        try:
            asset_id = UUID(evidence_asset_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid evidence asset ID") from exc
        try:
            return service.complete_part(principal, asset_id, part_number, payload)
        except EvidenceAssetNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except EvidenceCaptureRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EvidenceProviderUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Evidence storage is temporarily unavailable"
            ) from exc

    return app


def _build_local_entrypoint() -> FastAPI | None:
    """Keep the raw module entrypoint limited to local/test environments.

    The deployed entrypoint is ``backend.app.runtime:app``. Returning no ASGI
    application here for staging/production prevents the raw module from
    constructing an incomplete provider graph while the runtime composition
    root is being imported.
    """

    config = Settings.from_env()
    if config.environment in {"staging", "production"}:
        return None
    return create_app(config)


app = _build_local_entrypoint()
