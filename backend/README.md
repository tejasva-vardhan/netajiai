# AI Neta greenfield backend

This directory contains the production-oriented backend described in
`AI_Neta_Redesign_Plan.md`. It is the canonical API/application runtime for the
mobile and web clients.

The DigiLocker Requester transport is implemented in
`app/infrastructure/digilocker.py`. It follows the configured
authorization-code + PKCE, server-side token exchange, and authenticated user
details flow from the [official Requester API specification](https://entity.digilocker.gov.in/assets/img/Requester%20-%20Entity%20Locker%20API%20Specification_07_10_24.pdf).
It only persists allowlisted scalar claims and a verification result; it does
not download or store documents. The deployment composition module must inject
`build_digilocker_requester_transport(settings)` after partner onboarding and
claim review.

## Current slice

The citizen capture surface is the separate Expo app in `../apps/mobile/`.
Its setup, device testing, and explicit production gates are documented in
[`../apps/mobile/README.md`](../apps/mobile/README.md). The public/operator web
surface is in `../apps/web/`.

- `app/api/` owns FastAPI presentation and HTTP contracts.
- `app/application/` owns use-case ports and orchestration interfaces.
- `app/domain/` owns pure complaint lifecycle rules.
- `app/ai/` owns the provider-neutral Agno boundary; the local composition uses
  Mistral and deterministic tests use fakes.
- `app/application/drafts.py` exposes the authenticated, non-authoritative
  complaint extraction command at `POST /api/v1/complaints/draft`. It returns
  validated fields only; it cannot create, route, escalate, or transition a
  complaint.
- `GET /api/v1/complaints/categories` returns the versioned server-owned launch
  taxonomy used by tap-first mobile intake. It contains no operational data or
  citizen information; mobile may retain the last valid response for
  low-connectivity rendering.
- `app/infrastructure/routing.py` contains the bounded synthetic MP routing
  adapter. It can mark only the documented synthetic Bhopal fixture as active;
  missing, low-accuracy, and out-of-zone evidence stays in
  `mapping_in_progress`. It must not be enabled as live operations routing.
- `app/application/complaints.py` owns the evidence-gated complaint command.
- `app/application/tone_governor.py` is the deterministic, injectable safety
  boundary for casual conversation. It refuses political, medical, legal,
  financial-advice, and explicit threatening-language turns without rewriting
  complaint facts; filing and reviewed scheme handlers remain constrained
  paths.
- `app/application/department_replies.py` and
  `app/infrastructure/department_replies.py` record private operator/department
  replies at the workflow-signal boundary. The normalized reply is retained
  only in the private database record; its hash and classification are used for
  idempotency and weak/duplicate signals. Raw text is never sent to Temporal,
  lifecycle events, logs, or public projections.
- `app/application/issue_clusters.py` defines the versioned deterministic
  candidate policy. During complaint persistence, only verified server-owned
  evidence location is considered; reports are linked without merging their
  complaint lifecycles, and supporter counts use keyed supporter references.
  The private complaint/tracking and admin projections may show the aggregate
  count; the public receipt projection deliberately does not.
- `app/application/evidence.py` owns the direct-upload, capture-attestation,
  hash-verification, and media-inspection workflow.
  The attestation port receives the server-derived citizen subject and the
  citizen-scoped idempotency key, so a production provider can reject
  cross-citizen and cross-request token reuse.
- `POST /api/v1/evidence/capture-sessions` issues a short-lived signed browser
  capture session only to an identity-verified citizen. Browser camera/audio
  evidence is explicitly labelled, bound to the citizen and upload key, and
  remains `review_required` by default. `WEB_CAPTURE_REVIEW_REQUIRED=false`
  is an explicit production policy decision, not a browser trust claim.
- `app/infrastructure/identity.py` owns the deterministic verification
  boundary, while `app/infrastructure/digilocker.py` owns both the injectable
  Requester HTTP transport and the explicitly temporary local account
  verification transport. The local transport is composed only for
  development/test and never represents government identity; the Requester
  transport is composed after the provider contract and claims are approved.
- `app/application/identity.py` owns the provider-neutral authorization-code
  flow with state, PKCE, nonce, and authenticated-subject binding.
  `app/infrastructure/identity_authorization.py` encrypts short-lived PKCE
  material at rest; provider-specific token/document calls remain behind the
  approved Requester transport port.
- `GET /api/v1/identity/digilocker/status` returns only the signed-in
  citizen's provider/status/timestamps. It never returns DigiLocker claims or
  documents. Complaint, draft, and evidence commands use the persisted
  verification result as the server-side authority: it can restore a verified
  state when the OIDC token has not refreshed its claim and can revoke a stale,
  expired, pending, or rejected token claim. Conversation filing handoffs use
  the same authority, so a citizen returning from DigiLocker does not need a
  token refresh before the assistant can offer the verified filing path.
- `GET /api/v1/admin/complaints` is the first operator/admin read contract. It
  requires a server-derived `operator`, `admin`, or `moderator` role, supports
  bounded keyset pagination and routing/status filters, and returns no citizen
  identifier or raw complaint description. The privileged web control tower is
  still a separate deliverable.
- `GET /api/v1/admin/overview` is the aggregate control-tower read contract. It
  exposes only complaint counts by lifecycle status and execution-zone state,
  escalation count, mapping backlog, and latest update time; it never returns
  citizen identity, complaint text, or precise location.
- Uncertain automated media inspection enters `review_required` rather than
  silently deciding acceptance. Operators use
  `GET /api/v1/admin/evidence/review-queue` and the idempotent review command
  to approve or reject it. Queue responses contain no citizen identity,
  complaint text, location, or object key; previews are short-lived grants from
  the injected object-store adapter. The native capture path propagates this
  state and does not submit a complaint until the evidence is verified; queued
  captures retry after approval, while terminally rejected evidence is not
  retried automatically.
- `POST /api/v1/conversations/turn` is the bounded multi-handler conversation
  boundary. It classifies one turn, persists structured session context plus a
  bounded latest-response snapshot for exact idempotent replay (never raw turn
  text), passes that compact context to the router/extractor, returns
  deterministic handoff instructions, and avoids repeating a model/provider
  call on a completed retry. Filing extraction is available only to a verified
  principal; scheme turns query only approved, current, source-cited records
  and otherwise use an explicit unavailable response.
- `POST /api/v1/schemes/answer` exposes the same grounded scheme handler for
  clients that need a direct contract. It filters by language, jurisdiction,
  validity, scheme review, and source review. No endpoint fetches arbitrary
  documents or approves content automatically; records enter through the
  authenticated staging/approval review endpoints below.
- `POST /api/v1/admin/complaints/{complaint_id}/department-response` and
  `POST /api/v1/complaints/{complaint_id}/citizen-confirmation` are typed,
  idempotent Temporal signal commands. The first requires an operator
  capability; the second requires authenticated ownership of the complaint and
  is accepted only while the workflow is waiting for the citizen outcome.
  Both persist a PostgreSQL receipt before calling the injected workflow
  sender, and return `503` when that sender cannot accept the signal. Routing
  activation uses the same boundary at
  `POST /api/v1/admin/complaints/{complaint_id}/routing-activation`; it takes
  an empty typed request, resolves the decision through a server-owned
  adapter, persists the routing snapshot, and then signals Temporal.
- `app/application/outbox.py` and `app/infrastructure/queues.py` own bounded
  outbox dispatch and the Kafka publisher; delivery is at-least-once and
  consumers must deduplicate by `message_id`/`event_id`.
- `app/application/notifications.py` and
  `app/infrastructure/notifications.py` own the durable notification delivery
  boundary. It records only template metadata, destination-reference hashes,
  attempts, provider receipts, and bounded error codes. A provider adapter must
  honor the same idempotency key; the fake sender is test-only and no real
  email, SMS, WhatsApp, push, or voice channel is enabled by default.
- `app/workflows/` owns the deterministic Temporal complaint lifecycle,
  structured signals, replay-safe transition activity, and worker factory.
  `app/infrastructure/temporal.py` starts one idempotent workflow per
  complaint; an outbox consumer will call it after the database commit.
- `app/workers/` contains separate outbox polling, Kafka event-consumer, Temporal,
  and evidence-cleanup runtimes. They have explicit signal handling and do not
  run as import-time or API-startup side effects. The evidence cleanup worker
  claims stale multipart sessions in PostgreSQL before calling S3 abort, keeps
  transient failures retryable, and marks successfully reclaimed sessions as
  rejected with a bounded reason code.
- `app/infrastructure/tracking.py` signs opaque public receipt tokens; the
  public tracking endpoint returns a redacted projection and never accepts a
  client-supplied citizen ID.
- `app/config.py` rejects unsafe production configuration.
- `app/observability.py` configures the OpenTelemetry API/SDK and optional
  OTLP/HTTP export. Local/test environments use the no-op API; production
  requires an explicit collector endpoint. HTTP spans and metrics contain only
  bounded method, route-template, status, and duration dimensions—never body,
  query, token, or complaint text.
- `docs/contracts/` contains the generated OpenAPI v1 artifact and the
  `complaint.lifecycle.v1` JSON Schema. Queue consumers and the outbox producer
  validate that lifecycle payload against the same versioned Pydantic contract.
- `app/application/rate_limits.py` defines named abuse-control policies and a
  provider-neutral shared-store port. Identity, direct-connection IP, and
  optional device signals are hashed before use; forwarded-IP headers are not
  trusted by default.
- The API generates or validates an `X-Request-ID`, returns it on every HTTP
  response, and uses only route templates plus bounded timing/status metadata
  in request logs. URL values, request bodies, tokens, and provider error text
  are not logged by this middleware. The OTel collector, dashboards, alarms,
  and retention policy remain deployment actions.
- Infrastructure and provider failures return stable, user-safe 5xx messages;
  raw exception text is not exposed through the HTTP error contract. Controlled
  validation and idempotency conflicts retain their bounded client-facing
  reason messages.
- `tests/` contains deterministic tests that do not call live AI, DigiLocker,
  messaging, or Temporal services; workflow tests use Temporal's local test
  environment.

Run the slice from the repository root:

```bash
python -m pytest backend/tests
uvicorn backend.app.api.main:app --reload --port 8001
```

The container/deployment entrypoint is `backend.app.runtime:app`. It loads
the module named by `COMPOSITION_MODULE` in staging/production; that module
must expose `build_adapters(settings)` and return
`backend.app.runtime.RuntimeAdapters`. This is the only supported place to
construct provider SDK clients and inject them into the API. If the module or
any required staging/production adapter is missing, startup fails closed. Local/test
development may continue to use `backend.app.api.main:app` with explicit test
overrides.

Run the migration command from `backend/` only after setting `DATABASE_URL`:

```bash
cd backend
APP_ENV=development python -m alembic -c alembic.ini upgrade head
```

The migration is PostgreSQL/PostGIS-oriented and includes append-only database
triggers for complaint events, private department replies, and private
silence events. The silence event is written by the Temporal activity before
the deterministic escalation transition; it contains deadline metadata, not
raw complaint or reply text. It is not run automatically at application
startup.

Revision `0024_postgis_location_points` enables the PostGIS extension and adds
an immutable `geography(POINT, 4326)` representation plus a GiST index for
server-side spatial queries. The current routing adapter still uses the
bounded synthetic MP fixture; live jurisdiction boundaries and operations
contacts remain intentionally deferred. The local Compose database uses the
official PostGIS image so the migration path is testable without a separate
database setup.

`POST /api/v1/evidence/capture-sessions` is the browser-capture boundary. It
requires an authenticated, identity-verified citizen and a citizen-scoped
idempotency key. The signed session is bound to the citizen, asset type, and
key; browser evidence is labelled separately and remains `review_required`
until the configured media/reviewer policy accepts it. `WEB_CAPTURE_ENABLED`
is false by default and must not be treated as native device attestation.

Revision identifiers are kept within Alembic's 32-character version-table
limit. The migration test suite checks this invariant so a future migration
cannot pass local ORM tests and then fail during a PostgreSQL release job.

Complaint creation also persists an immutable SLA snapshot: policy version,
initial response timeout, and post-escalation timeout. The outbox includes the
snapshot so Temporal uses the accepted policy even if configuration changes
later. `SyntheticSlaPolicy` is limited to development and controlled fixtures;
staging/production application construction requires an injected `sla_policy`
adapter.

The Kafka publisher is provider-backed but not started by the API process. A
separate worker constructs `SqlAlchemyOutboxRepository` and
`KafkaOutboxPublisher` with `KAFKA_BOOTSTRAP_SERVERS`; it runs bounded
`OutboxDispatcher.dispatch_once` batches. The event worker consumes the
versioned envelope, commits offsets only after successful handling, starts the
`complaint-lifecycle-v1` workflow for `complaint.received`, and leaves failed
records uncommitted for Kafka redelivery and the configured retention/DLQ
policy.
The Temporal worker is likewise constructed through `create_worker`, with a
configured `TEMPORAL_TARGET`, `TEMPORAL_NAMESPACE`, and
`TEMPORAL_TASK_QUEUE`; the API does not open a Temporal connection as an
import/startup side effect.

The authenticated `GET /api/v1/complaints/{complaint_id}` projection includes a
citizen-safe lifecycle timeline reconstructed from append-only lifecycle and
silence events. It contains status, event type, safe reason code, escalation
level, and timestamps only; raw event payloads, actor identifiers, department
replies, and precise location are not returned. The receipt-token public
projection remains point-in-time and redacted until public timeline policy is
approved.

The greenfield API exposes `/health` as a process liveness check and `/ready`
as a bounded database-readiness check, plus `POST /api/v1/evidence/uploads`,
`POST /api/v1/evidence/{evidence_asset_id}/parts/{part_number}` for multipart
part receipts, `POST /api/v1/evidence/{evidence_asset_id}/complete`, and the
first versioned complaint command, `POST /api/v1/complaints`. Small evidence
uses a single short-lived presigned PUT; assets at or above 10 MiB use a
provider-neutral multipart session with 5 MiB parts, durable part receipts,
retry-safe completion, and final object integrity verification. The API never
proxies media bytes. Complaint
creation accepts only server-owned verified evidence asset IDs and writes the
complaint, its durable evidence links, append-only lifecycle event, and
transactional outbox message together. Complaint and evidence-upload
idempotency keys are bound to request fingerprints; a reused key with different
metadata returns a conflict. `GET /api/v1/complaints/{complaint_id}` is
citizen-scoped and returns an explicit tracking contract; cross-citizen
lookups return not found. No user-visible workflow is stored in process memory.

The S3 multipart adapter completes uploads with the recorded SHA-256 checksum
for every part, an explicit composite checksum type, and the expected total
object size; object metadata is not treated as the integrity proof by itself.
This follows [S3 multipart checksum guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html).

`POST /api/v1/complaints/{complaint_id}/transitions` is restricted to principals
with the `workflow`, `operator`, or `admin` capability. It rebuilds the
aggregate from persisted state, enforces the deterministic transition table,
and records an idempotent event/outbox pair. Citizens cannot submit arbitrary
status changes. Transition keys are fingerprinted so a retry with different
state or escalation metadata is rejected. The Temporal path caps automatic
escalation at L4 and records disclosure-review eligibility; publication still
requires the approved policy and consent path.

The department-response command requires a typed proof reference when the
outcome is `fix_reported`. A configured verifier must accept it before a
durable, complaint-bound proof claim is created; persistence stores only the
proof type, verifier, timestamps, and SHA-256 reference hash. The raw proof
reference is not sent to Temporal or written to workflow history. The
`UnconfiguredClosureProofVerifier` fails closed, while
`FixtureClosureProofVerifier` is test-only.

`GET /api/v1/public/complaints/{tracking_token}` accepts only a server-signed
receipt capability returned once from complaint creation. It exposes status,
category, execution-zone state, and timestamps, but not citizen identity, raw
description, jurisdiction precision, or location data. Configure
`PUBLIC_TRACKING_TOKEN_SECRET` through the secret manager before enabling this
path in production.

`GET /api/v1/public/transparency` is a separate, policy-gated aggregate
projection. When `PUBLIC_TRANSPARENCY_ENABLED=true`, it returns only total,
status, execution-zone, escalation, and mapping-in-progress counts plus
bounded freshness/policy metadata. It never returns complaint IDs, citizen
identity, raw text, department contacts, exact locations, or evidence. The
flag is false by default; product/legal must approve suppression, redaction,
retention, and publication policy before enabling it.

`POST /api/v1/complaints/{complaint_id}/disclosure-consent` records the
authenticated citizen's explicit, one-time disclosure choice with the
server-owned `PUBLIC_DISCLOSURE_POLICY_VERSION` and an idempotency key. The
client cannot choose the policy version. The command writes an append-only
audit/outbox event and stores no citizen name or raw evidence in the consent
record.
`PUBLIC_DISCLOSURE_ENABLED=false` is the safe default; public-name consent
returns a policy-unavailable response until product/legal approval is recorded
and the deployment explicitly enables the versioned policy.

`PUBLIC_TRANSPARENCY_ENABLED=false` is also the safe default. Before enabling
the aggregate dashboard, product/privacy/legal must approve its suppression,
redaction, freshness, and retention policy and set the approved
`PUBLIC_TRANSPARENCY_POLICY_VERSION`; the endpoint never substitutes for
case-level disclosure consent.

Scheme knowledge has a separate source-review boundary. Operators can stage a
structured, source-backed record at `POST /api/v1/admin/schemes`; it remains
`pending_review`, requires HTTPS source metadata, and is naturally idempotent
for the same scheme/language/version and content. Only a moderator or admin
can approve it through
`POST /api/v1/admin/schemes/{scheme_id}/approve`; approval records the reviewer
identity on both the scheme and its sources. Public scheme answers continue to
require approved, current records and approved sources. The review endpoints do
not fetch arbitrary documents or mark content approved automatically.

The multipart evidence path is reclaimed by the separate
`aineta-evidence-cleanup-worker`. It considers multipart sessions abandoned
after `EVIDENCE_CLEANUP_AGE_SECONDS` (24 hours by default), claims them with a
database-backed lease, calls the provider's idempotent abort operation, and
retries failures after `EVIDENCE_CLEANUP_RETRY_AFTER_SECONDS`. Configure the
batch and interval values in the environment and run the worker against the
same database and private S3 bucket as the API.

The default app has no authentication resolver, database session factory,
production evidence verifier, capture attestation verifier, object store, or
media inspector, so user-visible commands fail closed until those adapters are
configured. `AcceptedEvidenceFixture`, `FixtureCaptureAttestationVerifier`,
`InMemoryObjectStore`, and `MetadataInspectionFixture` are test-only and must
never be wired into staging or production.

## Production configuration gates

`APP_ENV=production` requires explicit database, Mistral model/key, Deepgram
model/key,
DigiLocker mode, identity-state encryption key, Temporal target/namespace/API
key/task queue, allowed
origins, S3 object storage, capture attestation, media inspection adapters,
closure proof verification, speech-to-text, OIDC configuration, shared
rate-limit protection, OpenTelemetry OTLP export, Kafka bootstrap/topic/group,
and the
32-byte-plus `ISSUE_CLUSTER_HMAC_KEY`. `fake`
AI and local DigiLocker modes are rejected in production. Credentials belong in
the host’s secret manager; never commit them to this repository.
The OIDC issuer/JWKS, DigiLocker endpoints and redirect URI, and
allowed origins must also be absolute HTTPS URLs with a host; malformed values
are rejected before the application starts.
The production PostgreSQL service must permit the `postgis` extension for the
migration chain through `0026_voice_draft_request_binding`; the migrations must
run as an explicit release job, not during API startup.

Agno is represented by a provider-neutral port and a Mistral adapter. The
greenfield runtime dependencies are pinned in `pyproject.toml` and resolved in
`uv.lock`/`requirements.lock`; the verified baseline is `agno==2.6.5`,
`mistralai==2.9.2`, and `confluent-kafka==2.15.0`. Re-run the factory and
structured-output tests,
license/model-provider review, and image build whenever a dependency changes,
as required by `AGENTS.md`.

The lazy construction adapter is available at
`backend.app.infrastructure.ai.build_agno_orchestrator`. It supports
`AI_PROVIDER=mistral`, uses the configured `AI_MODEL`, applies the bounded
`AI_REQUEST_TIMEOUT_SECONDS` provider deadline, and creates three tool-free
agents behind one provider-neutral port (intent routing, complaint extraction,
and bounded casual chat), and makes no provider call during construction. The
deployment composition root must inject its result into `create_app`; the API
does not silently construct a model client or fall back to a fake in production.
Supply `MISTRAL_API_KEY` through the secret manager; the test suite never calls
the provider. The current local voice adapter is `DeepgramSpeechToText` using
`DEEPGRAM_API_KEY` and the configured prerecorded model. Re-run the factory,
structured-output, speech, lockfile, and image tests whenever either provider
dependency is upgraded.

Voice drafting is exposed at `POST /api/v1/complaints/voice-draft`. It accepts
only a citizen-owned, server-verified audio asset, sends its server-owned
metadata to an injected `SpeechToText` adapter, and passes the returned text
through the same bounded complaint extractor as text drafting. A required
citizen-scoped `Idempotency-Key` binds retries to the same audio asset and
language; retries re-run the bounded draft flow because the transcript-derived
read-back is not persisted. The raw transcript is never stored in the
voice-draft request table. The local composition uses Deepgram's prerecorded
transcription endpoint for verified audio and maps Hinglish to automatic
language detection. Provider/model selection, language quality evaluation,
quotas, and human fallback remain deployment decisions.

## Local activation notes

Global launch gates are maintained in
[`../docs/ACTION_REQUIRED.md`](../docs/ACTION_REQUIRED.md).

- Verification-start requests use the stricter `identity` policy; authenticated
  status reads use the separate `identity_status` policy so normal page loads,
  refreshes, and provider return polling do not exhaust the start-flow bucket.
  Rate-limit and `Retry-After` headers are exposed to the web client.

- Finance/platform must replace the example `AI_MONTHLY_REQUEST_LIMIT` and
  `VOICE_MONTHLY_REQUEST_LIMIT` values with approved launch caps, then configure
  provider-level currency alerts and quota alarms. The application caps are
  fleet-wide fixed-window request guards, not a substitute for provider billing
  controls. Both values are required explicitly for staging and production;
  startup fails closed when either is absent. Verify them with the shared
  Redis-compatible limiter in staging; local in-memory limits are
  test/development-only.

- Deployment engineering must package the approved provider implementations
  in the module named by `COMPOSITION_MODULE`. Its
  `build_adapters(settings)` function must return
  `backend.app.runtime.RuntimeAdapters`; do not use test fixtures or a
  process-local substitute for staging/production. The deployment entrypoint
  fails closed when this module or any required adapter is absent.
- Engineering must configure the selected OIDC issuer’s `OIDC_ISSUER`,
  `OIDC_JWKS_URL`, `OIDC_AUDIENCE`, and approved `OIDC_ALGORITHMS` values in
  the secret/config manager. The deployment composition module must construct
  and inject the fail-closed JWKS-backed verifier; the API does not construct
  provider clients itself. It accepts only signed, issuer/audience-checked
  asymmetric tokens.
- Legal/security and engineering must complete DigiLocker Requester onboarding,
  consent wording, minimum-claim selection, retention/deletion rules, and the
  provider-specific endpoint contract before production identity use. The OAuth
  state/PKCE/callback boundary and injectable authorization-code/user-details
  transport are implemented; raw document retrieval is intentionally not part
  of this verification path.
  Obtain the partner account through the [API Setu partner registration flow](https://partners.apisetu.gov.in/signup), then configure
  `DIGILOCKER_CLIENT_ID`, `DIGILOCKER_CLIENT_SECRET`,
  `DIGILOCKER_AUTHORIZATION_ENDPOINT`, `DIGILOCKER_TOKEN_ENDPOINT`,
  `DIGILOCKER_USER_ENDPOINT`,
  `DIGILOCKER_REDIRECT_URI`, `DIGILOCKER_SCOPE`, and
  `DIGILOCKER_PURPOSE` in the secret/config
  manager. Verify the callback URL, approved scope, consent flow, and sandbox
  test account before enabling `DIGILOCKER_MODE=requester`.
- Platform engineering must provision `IDENTITY_STATE_ENCRYPTION_KEY` through
  the secret manager and use the same key for all API instances that may
  receive the OAuth callback. Never place the generated key in source control.
- Engineering must replace the test capture/media fixtures with approved
  native-capture attestation, malware/clarity/reuse inspection, and human
  review adapters; the durable metadata and direct-upload contract is already
  implemented.
- Product/privacy must approve the issue-cluster policy before exposing any
  cluster information publicly: cell precision, category/time-window matching,
  minimum supporter threshold, abuse controls, retention, human review, and
  redaction. Until then, cluster links are internal, non-destructive candidate
  metadata only. `ISSUE_CLUSTER_HMAC_KEY` must be a separate 32-byte-plus
  secret shared by all API instances.
- Engineering and product/legal must select and inject the approved closure
  proof verifier, proof-type policy, retention period, and review path. The
  typed claim, hash-only persistence, idempotency, and workflow guard are
  implemented; the test fixture must not be used outside tests.
- Product/legal/security must approve department-reply retention/deletion,
  operator access, silence-event retention/deletion, and review policy before
  real provider replies or delay analytics are enabled. Weak/substantive/
  duplicate classification is a review signal only; silence recording does
  not reset an SLA or mutate complaint state.
- Platform engineering must inject a shared Redis-compatible `RateLimiter` for
  staging and production, configure the WAF/edge policy and trusted-proxy
  boundary, and verify 429/retry behavior across more than one API instance.
  `NoopRateLimiter` and `InMemoryRateLimiter` are test/development fixtures and
  are rejected by production app construction.
- Product/operations/platform must provide the versioned category SLA policy
  and inject it as `RuntimeAdapters.sla_policy` for staging/production. The
  policy must define response and post-escalation targets, calendar/pause
  behavior, effective version, owner, and review process. The synthetic SLA
  fixture is not a production fallback.
- Platform engineering must deploy the Temporal worker and the Kafka outbox
  publisher plus the Kafka event worker with bounded concurrency, retry/backoff,
  metrics, and idempotent handling. The workflow itself is tested locally
  against Temporal's test environment; no live Temporal or Kafka service is
  contacted by the test suite. The package exposes
  `aineta-outbox-worker`, `aineta-event-worker`, and
  `aineta-temporal-worker` entrypoints. Deploy
  `aineta-evidence-cleanup-worker` as a separate bounded process as well; its
  database claim/abort/retry behavior is covered by deterministic tests.
  Keep task secrets role-scoped: outbox needs the database and event queue;
  events needs the event queue and Temporal connection; Temporal needs the
  database and Temporal connection; cleanup needs the database and S3 settings.
  These workers must not receive the API-only DigiLocker, OIDC, or AI secrets.
- The API composition root must inject a production
  `WorkflowSignalSender` backed by the approved Temporal client. Configure
  the same Temporal namespace/task queue used by the worker, test duplicate
  signals and retry-after-failure in staging, and keep the API fail-closed if
  this adapter is missing. The API does not open a Temporal connection during
  import or startup.
- The API composition root must also inject a production
  `RoutingActivationResolver` backed by the approved, versioned
  jurisdiction/contact authority. It must return the active-zone decision and
  routing snapshot from server-owned data; the routing-activation request
  cannot supply jurisdiction, contacts, SLA values, or coordinates. Synthetic
  routing fixtures remain limited to local and controlled testing.
- Notification provider activation is a separate gate: choose an approved
  provider, implement its adapter against the `NotificationSender` port, verify
  provider-side idempotency and delivery webhooks, and configure a bounded
  retry/DLQ policy. Do not place raw citizen phone numbers or email addresses in
  notification delivery records. Telecom-specific activation remains deferred
  by product decision.
