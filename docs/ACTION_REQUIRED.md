# AI Neta — Action Required Before Live Activation

This is the canonical launch-control checklist for decisions, credentials,
provider onboarding, and deployment actions that the repository cannot safely
invent. It is separate from the redesign plan so outstanding work is easy to
find and track.

Engineering can continue locally with the Docker Compose profile documented in
[`LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md) while these gates are completed.
That profile uses Mistral, Deepgram, Kafka, Redis, MinIO, Keycloak, and
Temporal; only the Mistral and Deepgram API keys remain external setup actions.

The current decisions intentionally exclude live operations data and telecom
provider work from this redesign stage. DigiLocker is the identity path to
onboard and verify for production.

## Product, privacy, and safety

- **ACTION REQUIRED — Product/legal:** approve the public disclosure and closure policies, redaction rules, consent language, and policy version before enabling `PUBLIC_DISCLOSURE_ENABLED=true`. The disclosure-consent command is implemented and remains private-by-default until this approval.
- **ACTION REQUIRED — Product/privacy/legal:** approve the aggregate transparency suppression, redaction, retention, freshness, and publication policy before enabling `PUBLIC_TRANSPARENCY_ENABLED=true`. The current endpoint is limited to global status/zone/escalation/mapping counts; it does not expose case-level data or replace the separate public-disclosure consent policy.
- **ACTION REQUIRED — Product/domain/safety:** approve the non-commercial priority policy before implementing priority scoring. Define allowed signals, levels, thresholds, explanation text, audit/versioning, appeal behavior, and an explicit prohibition on payment, identity, political influence, or AI-only decisions. Priority must remain separate from routing and escalation authority.
- **ACTION REQUIRED — Product/privacy:** approve the versioned duplicate/collective-issue policy: location-cell precision, category and time-window matching, minimum supporter threshold, abuse/brigading controls, human-review rules, retention, and what—if anything—may appear in public projections. Until then, candidate links remain internal and non-destructive.
- **ACTION REQUIRED — Product/privacy/mobile:** approve the maximum local `capture_queue` age and expiry behavior before a signed production build. Specify deletion of the SQLCipher row and OS-managed photo/audio files, the citizen-facing next-open message, and whether sign-out/session changes permanently expire queued captures. Record the approved policy/version in `apps/mobile/src/queue.native.ts` and verify expiry/cleanup on signed Android and iOS builds.
- **ACTION REQUIRED — Product/legal/security:** approve department-reply and silence-event retention/deletion, operator access, source verification, and weak-reply review policy before enabling real provider replies or exposing delay analytics.
- **ACTION REQUIRED — Product/research:** provide the approved scheme catalogue, source documents/URLs, jurisdictions, supported languages, effective/expiry dates, eligibility fields, reviewer, and review policy. Do not mark records `approved` or enable public scheme answers until source provenance and legal/content review are complete.
- **ACTION REQUIRED — Research:** recruit representative low-literacy, first-time, dialect, feature-phone, and low-bandwidth users for moderated testing.

## Identity and authentication

- **ACTION REQUIRED — Legal/security/platform:** complete [DigiLocker Requester/API Setu partner onboarding](https://partners.apisetu.gov.in/signup), obtain the approved Requester API specification and credentials, register the exact callback URL, and approve the OAuth/OIDC scope, `purpose=verification`, minimum scalar claims, retention/deletion policy, DPDP role mapping, India-region requirement, and provider contract. Configure `DIGILOCKER_CLIENT_ID`, `DIGILOCKER_CLIENT_SECRET`, `DIGILOCKER_AUTHORIZATION_ENDPOINT`, `DIGILOCKER_TOKEN_ENDPOINT`, `DIGILOCKER_USER_ENDPOINT`, `DIGILOCKER_REDIRECT_URI`, `DIGILOCKER_SCOPE`, and `DIGILOCKER_PURPOSE` only through the secret/config manager. Inject `build_digilocker_requester_transport(settings)` into the deployment-owned identity authorization factory and verify token exchange, user lookup, callback replay, expiry, revocation, and claim-minimization cases in the provider sandbox.
- **ACTION REQUIRED — Mobile/identity:** register the OIDC public client and `aineta://auth/callback` redirect for signed mobile builds; configure `EXPO_PUBLIC_OIDC_ISSUER`, `EXPO_PUBLIC_OIDC_CLIENT_ID`, and approved scopes in staging/release environments. Verify issuer, audience, subject mapping, expiry, and the post-DigiLocker verification state. No client secret may be shipped in the app.
- **ACTION REQUIRED — Web/platform/security:** deploy `apps/web` with `NEXT_PUBLIC_API_BASE_URL` pointing to the HTTPS greenfield API, register separate public OIDC callbacks for `/admin/auth/callback` and `/auth/callback`, set `NEXT_PUBLIC_OIDC_ISSUER`, `NEXT_PUBLIC_OIDC_CLIENT_ID`, citizen redirect variables, and approved scopes, add the web origin to backend CORS, and map provider `roles` to backend capabilities. Approve the capability matrix, bearer-token session/logout policy, browser privacy policy, and staging 401/403/expiry tests before enabling privileged access. No OIDC client secret may be shipped to the browser.
- **ACTION REQUIRED — Web/platform/privacy:** before enabling browser filing, set `WEB_CAPTURE_ENABLED=true` and provision `WEB_CAPTURE_SESSION_HMAC_KEY` of at least 32 bytes with a TTL no longer than 900 seconds. Keep `WEB_CAPTURE_REVIEW_REQUIRED=true` until browser media inspection, spoof/replay testing, human-review ownership, and the direct-verification policy are approved. This does not replace native device attestation.

## Platform, data, and workflow

- **ACTION REQUIRED — Platform/security:** generate a separate 32-byte-plus `ISSUE_CLUSTER_HMAC_KEY` in the deployment secret manager, share it consistently across API instances, and verify rotation/rebuild procedures before enabling production candidate matching.
- **ACTION REQUIRED — Platform:** configure `TEMPORAL_TARGET`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY`, `TEMPORAL_TASK_QUEUE`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC`, `KAFKA_CONSUMER_GROUP`, and `PUBLIC_TRACKING_TOKEN_SECRET`, then deploy the Temporal worker, Kafka outbox dispatcher, and Kafka event consumer. Supply live connections/secrets through the deployment secret/config manager.
- **ACTION REQUIRED — Platform/data:** provision production PostgreSQL with approved PostGIS extension privilege, run the migration chain through Alembic head `0026_voice_draft_request_binding` as an explicit release job, and verify the generated SRID-4326 point, GiST index, append-only citizen-resolution table, transcript-free voice-draft request binding, and foreign-key constraints in staging.
- **ACTION REQUIRED — Platform/engineering:** inject a production `WorkflowSignalSender` backed by the approved Temporal client into the API composition root, deploy it with the Temporal worker, and verify signal receipt/retry behavior in staging. The API fails closed when this adapter is absent.
- **ACTION REQUIRED — Platform:** build and scan [`infra/docker/backend.Dockerfile`](../infra/docker/backend.Dockerfile), run Alembic as an explicit release job, and create separate ECS task definitions for the API and each worker with immutable image digests, non-root/read-only settings, IAM, CloudWatch logging, health checks, CPU/memory limits, and secret-manager references.
- **ACTION REQUIRED — Platform/engineering:** package the deployment-owned `COMPOSITION_MODULE` with approved provider implementations. Its `build_adapters(settings)` must return `backend.app.runtime.RuntimeAdapters`; verify that staging/production uses managed configuration, no fixture is selected, and startup fails closed when required adapters are missing.
- **ACTION REQUIRED — Platform/security/finance:** enable and apply [`infra/terraform/`](../infra/terraform/) only after replacing example inputs with approved private subnets, security groups, ALB target group, KMS key/policy, scoped secret ARNs, immutable image digest, managed Kafka bootstrap/topic/group, OTLP endpoint, and bounded capacity values. Use encrypted, locked remote Terraform state and verify evidence-bucket retention, Kafka retention/dead-letter handling, CloudWatch retention, IAM access, and budget alarms.
- **ACTION REQUIRED — Platform/security:** inject a shared Redis-compatible rate-limit adapter for staging/production, configure WAF and trusted-proxy policy, and verify identity/IP/device dimensions, 429 headers, retry behavior, and cross-instance consistency. Process-local/no-op limiters are development/test-only.
- **ACTION REQUIRED — Platform/operations:** when live routing is approved, inject a production `RoutingActivationResolver` backed by the approved, versioned jurisdiction/contact authority. It must return server-owned active-zone decisions and snapshots and never trust jurisdiction, contact, SLA, or coordinate values from the request.
- **ACTION REQUIRED — Product/operations/platform:** when live SLA automation is approved, provide the versioned category SLA policy and inject it as `RuntimeAdapters.sla_policy` for staging/production. Synthetic timings remain development fixtures.
- **ACTION REQUIRED — Product/operations:** approve the versioned follow-up target for a `partially_solved` citizen outcome and include it in the SLA policy before live automation.

## Finance, AI, and mobile delivery

- **ACTION REQUIRED — Finance/platform:** set the exact limited monthly ceiling, replace example `AI_MONTHLY_REQUEST_LIMIT` and `VOICE_MONTHLY_REQUEST_LIMIT` values, and configure provider currency alerts, per-provider quotas, token/media limits, and Temporal Cloud/S3/Kafka/Mistral/Deepgram spending alerts before paid traffic. Start with one small API/worker capacity profile and scale from measured usage.
- **ACTION REQUIRED — Engineering/legal:** record the license, model-provider terms, persistence/retention behavior, and production-support review for pinned `agno==2.6.5`, `mistralai==2.9.2`, `confluent-kafka==2.15.0`, and the selected Deepgram API/model. Re-run compatibility and image checks before dependency upgrades.
- **ACTION REQUIRED — Engineering/product/legal:** select and inject the approved closure-proof verifier, proof-type policy, retention period, and human-review path. The explicit fixture verifier must not be used outside tests.
- **ACTION REQUIRED — AI/platform:** approve the Deepgram speech-to-text adapter/model, record provider/model/language versions, set per-request and monthly quotas, evaluate noisy Hindi/English/Hinglish and dialect audio, and define human fallback thresholds. The local profile uses Deepgram; production still requires the reviewed provider configuration and evaluation evidence.
- **ACTION REQUIRED — AI/platform:** provide a reviewed, privacy-safe multilingual evaluation set and approve minimum intent/extraction/safety thresholds. Run it against the pinned Agno/model configuration and block production rollout on regressions. See [`docs/AI_EVALUATION.md`](AI_EVALUATION.md).
- **ACTION REQUIRED — Mobile/platform:** create EAS projects and signed development/release builds, set HTTPS `EXPO_PUBLIC_API_BASE_URL`, and replace the development-only `ConfiguredCaptureAttestationProvider` in `apps/mobile/src/capture.ts` with the approved native attestation adapter. Verify camera, GPS, audio, object-store upload, idempotency, cleanup, and background tasks on real devices.

## Deferred by current decision

- **Operations data:** intentionally skipped for this redesign stage. Use synthetic MP districts, contacts, calendars, and SLA fixtures. Live activation requires verified hierarchy, contacts, active districts, calendars, and SLA targets.
- **Telecom specifics:** intentionally skipped for this redesign stage. Keep channel boundaries and fakes only. Activation requires an approved provider, consent, templates, webhooks, and delivery policy.

Live identity verification, verified native capture, outbound messaging, and
paid production deployment remain gated by the items above.

## Explicitly deferred for now

Observability is intentionally skipped for the current local profile. OpenTelemetry
export is disabled (`OTEL_ENABLED=false`, `OTEL_EXPORTER=none`); the application
continues to emit bounded structured logs and the existing no-op telemetry path.
Before staging/production activation, provision an in-network collector, enable
OTLP/HTTP, define retention/access policy, and add dashboards and alerts.
