# AI Neta threat model and privacy review

Status: implementation review for the greenfield baseline
Last reviewed: 2026-08-06
Scope: `backend/app`, `apps/mobile`, `apps/web`, workers, migrations, and the
launch profile in `infra/terraform/`

This document records the security and privacy assumptions that must hold
before AI Neta accepts real citizen identity data or sends real outbound
department messages. It describes the current implementation, not an
assertion that the deferred production providers have already been approved.

## 1. Security objectives

AI Neta must preserve:

1. **Citizen control:** only the authenticated citizen can create, read, and
   confirm their private complaint data; a receipt token exposes only the
   intentionally redacted public projection.
2. **Evidence integrity:** a complaint cannot be submitted from an unverified
   or non-owned evidence asset, and the server—not the client or an AI model—
   decides whether evidence, routing, status, escalation, or closure is valid.
3. **Accountability integrity:** complaint events, replies, silence facts,
   consent, proof claims, and delivery receipts are append-only or otherwise
   idempotently auditable.
4. **Privacy by default:** raw complaint text, precise location, identity
   claims, media, tokens, provider credentials, and operator reply text do not
   enter public projections, logs, workflow signals, or analytics unless an
   approved policy explicitly permits a derived form.
5. **Safe failure:** missing or unapproved production adapters fail closed;
   the platform must not guess a government contact, silently send to an
   unverified destination, or mark a complaint resolved without the required
   proof and citizen outcome.

## 2. System and trust boundaries

```text
Citizen device / browser
        │  HTTPS, bearer session, receipt token, direct object upload
        ▼
FastAPI API boundary ──────── PostgreSQL source of truth
        │                              │
        │ outbox / validated events     │ append-only events + private records
        ▼                              ▼
Kafka / workers ───────────── Temporal workflows
        │                              │
        ├── object-storage adapter     ├── deterministic domain activities
        ├── DigiLocker adapter         └── typed, redacted signals
        ├── Agno/STT adapters
        └── notification adapters
```

The important boundaries are:

- **Untrusted client boundary:** all request fields, browser state, device
  identifiers, media metadata, GPS claims, and receipt tokens are attacker
  controlled until validated. Citizen identity comes from the server-side
  authentication adapter.
- **Provider boundary:** DigiLocker, OIDC, object storage, geocoding/routing,
  AI/STT, notification, Kafka, and Temporal are external systems. They are
  accessed only through narrow application ports and runtime-owned adapters.
- **Operator boundary:** operator/admin/moderator capabilities are distinct
  from citizen capabilities. Provider roles are mapped through the server-owned
  [`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md); operator APIs return redacted
  summaries and require named capabilities derived from verified roles.
- **Public projection boundary:** public tracking is a capability-token read,
  not an authenticated private read. It must never be expanded by returning
  ORM objects or private timeline fields.
- **Workflow boundary:** Temporal is not the source of truth. Workflow input
  and signals contain typed, minimal data; PostgreSQL/domain commands own
  state transitions and audit facts.

## 3. Assets and data classification

| Asset | Classification | Authoritative store/use | Required control |
|---|---|---|---|
| OIDC subject, DigiLocker reference, verification outcome | Restricted identity | PostgreSQL identity records | Encryption, minimum claims, expiry/retention, citizen scope, access audit |
| Raw complaint description and department reply | Restricted citizen case data | PostgreSQL private records | Ownership/capability checks, no logs/events/workflow/public copy unless policy allows |
| Photo, audio, location sample, hashes | Sensitive evidence | Object storage plus metadata | Native-capture policy, ownership, short-lived grants, checksum/size checks, retention and malware review |
| Complaint lifecycle events and silence facts | Confidential accountability data | Append-only PostgreSQL records | Immutable triggers, policy/correlation IDs, redacted projections, idempotency |
| Receipt token and bearer access token | Secret/capability | Client secure storage / request header | High entropy, HTTPS, no logs/analytics, rotation/expiry, no client-controlled identity |
| Routing/contact/SLA snapshots | Controlled operational data | PostgreSQL complaint snapshot | Versioning, verified source, effective dates, no AI-generated destinations |
| Scheme source and eligibility facts | Reviewed public-content data | PostgreSQL reviewed catalogue | Source provenance, review identity, expiry, answer only from approved records |
| Metrics and public aggregates | Derived public data | Read models/projections | Aggregation thresholds, coarse location, consent/redaction, no small-cell re-identification |
| Provider credentials and encryption keys | Secret infrastructure data | Managed secret/KMS services | Secret manager, rotation, least privilege, never repository/config examples |

## 4. Threat register

Risk ratings are qualitative: **High** can expose identity/evidence or change
accountability outcomes; **Medium** can cause material abuse, outage, or
privacy loss; **Low** is bounded by another control but still requires testing.

| ID | Threat / abuse case | Risk | Current mitigation | Residual gate or test |
|---|---|---:|---|---|
| T-01 | IDOR: a citizen changes a complaint or evidence ID to read another case | High | Authenticated principal is server-derived; citizen-owned repositories and evidence ownership checks; cross-citizen tests | Run authenticated staging IDOR tests for every private route |
| T-02 | Receipt token enumeration or leakage exposes private case data | High | HMAC receipt tokens; public projection excludes identity, description, precise jurisdiction, and location; token values are not logged | Approve token TTL/revocation policy and test brute-force/rate-limit alarms |
| T-03 | Forged OIDC/DigiLocker identity or stale verification permits filing | High | OIDC issuer/audience/JWKS/algorithm/expiry checks; persisted DigiLocker status fallback; expired verification is rejected | Complete Requester onboarding, claim mapping, key rotation and negative integration tests |
| T-04 | Client forges capture, GPS, timestamp, or evidence ownership | High | Server-owned evidence metadata, citizen- and idempotency-bound native/browser capture-session port, checksum/size/content-type checks, routing reads server-owned location, browser captures are review-gated by default, production unconfigured adapters fail closed | Install approved native attestation and media inspection; test replay, screenshot, GPS spoof, cross-citizen token reuse, idempotency-key reuse, and reused media cases. A browser session signature is provenance binding, not native device attestation. |
| T-05 | Malicious media causes malware, parser, or resource exhaustion | High | Size/content-type limits, direct object upload boundary, no raw media in PostgreSQL, bounded upload parts | Add malware/clarity/reuse scanner, quarantine policy, image/audio parser sandbox, and retention cleanup |
| T-06 | Prompt injection makes AI invent a contact, eligibility rule, escalation, or status | High | Agno agents are tool-free and schema-constrained; domain commands own routing/status/escalation; scheme answers require approved records; Tone Governor is deterministic | Run reviewed multilingual extraction, hallucination, refusal, and tool-boundary evaluations before live AI |
| T-07 | AI output directly changes a complaint outcome | High | `AgentOrchestrator` returns extraction/intent only; no AI write authority; deterministic domain/workflow rules own transitions | Preserve port contract and add a negative test for every critical command |
| T-08 | Operator abuses broad privileges or views unnecessary PII | High | Capability checks for operator/admin/moderator routes; admin list and web control tower are redacted; browser access uses OIDC code+PKCE with an in-memory token boundary; role-specific boundary exists | Approve OIDC capability matrix, bearer-token session/logout policy, operator audit review, and staging expiry/401/403 tests before production |
| T-09 | Forged provider/webhook/reply repeats or mutates a workflow signal | High | Typed signal contracts, operator capability, deterministic signal IDs, PostgreSQL receipt/idempotency, raw reply text kept private | Add provider authentication/signature verification and replay tests when transport is selected |
| T-10 | Department claims a fix without proof or citizen confirmation | High | Typed proof claim, verifier port, complaint binding, hash-only workflow data, citizen-confirmation gate, fixture verifier blocked in production | Approve real proof verifier, retention, human review, and media/work-order policy |
| T-11 | Duplicate delivery creates duplicate complaints, uploads, notifications, or escalations | Medium | Citizen-scoped idempotency, request fingerprints, outbox/event deduplication, stable mobile capture keys, workflow signal receipts | Run retry-storm/property tests against PostgreSQL and Kafka/Temporal staging |
| T-12 | Workflow timeout or provider delay loses the accountability fact | High | SLA snapshot persisted at intake; Temporal timers; append-only silence event before escalation; L1–L4 cap | Inject approved calendar/pause policy and run clock/replay/failover simulations |
| T-13 | Public aggregates reveal a small citizen group or exact location | High | Public disclosure is disabled by default; raw location is absent from cluster/public records; public timeline is redacted | Approve k-threshold/cell precision/retention policy and run projection privacy tests |
| T-14 | Logs, traces, errors, analytics, or prompts leak PII/secrets | High | Structured bounded logs; route templates; no body/query/token/provider-error logging; raw transcripts not persisted by current slice | Verify collector redaction, sampling, retention, access, and alert payloads in staging |
| T-15 | Rate-limit bypass through IP/device/identity variation causes spend or abuse | Medium | Named per-route policies, hashed dimensions, Redis-compatible adapter port, production rejection of process-local limiter | Deploy shared limiter/WAF and test proxy/IP trust, 429 behavior, and distributed consistency |
| T-16 | Provider outage, wrong destination, or retry sends duplicate citizen data | High | Provider-neutral notification port, destination-reference hashing, delivery receipts, idempotency, fake sender; no live destinations currently enabled | Verify destination authority, consent/templates, provider signing, retry/backoff, and spend alarms |
| T-17 | Database compromise or backup exposes long-lived identity/evidence | High | Minimized identity claims, object storage separation, retention fields, scoped repositories, no raw documents by default, SQLCipher-protected native offline queue | Configure KMS/encryption, backup access, deletion/retention jobs, restore drills, signed-build queue migration and device-at-rest verification |
| T-18 | Deployment starts with a fake/unconfigured adapter | High | Staging/production composition module and required-adapter checks fail closed; Terraform disabled by default | Build/scan immutable image and verify startup/readiness with missing-adapter matrix |
| T-19 | Supply-chain or dependency change introduces unsafe behavior | Medium | Pinned lockfiles, container build, lint/type/test gates, provider ports | Run dependency/license/image scans and record Agno/Mistral/Deepgram/Expo review before upgrades |
| T-20 | National traffic causes cost or availability collapse | Medium | Managed low-operations baseline, fleet-wide fixed-window AI/voice request caps, bounded model/media calls, quotas, Kafka/Temporal boundaries, rate limits | Set exact budget ceiling, alerts, load/soak tests, autoscaling and restore targets |

## 5. Privacy review decisions

The implementation follows these privacy decisions:

- **Purpose limitation:** DigiLocker is used for citizen verification, not as a
  general document store. Raw documents and unneeded claims are not persisted.
- **Data minimization:** public and admin projections contain only fields needed
  for their purpose. Department reply text, raw complaint text, actor IDs, and
  precise location remain private.
- **User control:** disclosure consent is an explicit, one-time command and is
  private-by-default. A citizen can track privately with an authenticated
  session or with a redacted receipt token.
- **Retention:** every restricted record type needs an owner, retention period,
  deletion mechanism, and legal basis before live activation. The current
  schema records expiry/deadline fields where the provider contract requires
  them but does not invent a legal retention period.
- **Access review:** operator/admin access must be least-privilege and audited;
  the web control tower is a bounded redacted surface, but it is not a
  substitute for an approved production capability matrix and session policy.
- **Location protection:** precise coordinates are used for server-side routing
  and evidence verification only. Public area views require a reviewed coarse
  aggregation and minimum group threshold.
- **Model privacy:** raw citizen complaints and personally identifying data are
  not placed in evaluation fixtures. Provider retention, training use, region,
  and deletion terms must be approved before live AI traffic.

## 6. Current controls mapped to code

- Authentication and DigiLocker boundaries: `backend/app/application/identity.py`,
  `backend/app/infrastructure/identity.py`, and
  `backend/app/infrastructure/digilocker.py`.
- Domain authority and transitions: `backend/app/domain/complaints.py` and
  `backend/app/application/complaints.py`.
- Evidence ownership and upload state: `backend/app/application/evidence.py`
  and `backend/app/infrastructure/evidence_repositories.py`.
- Routing and SLA policy ports:
  `backend/app/application/routing.py`,
  `backend/app/application/routing_activation.py`, and
  `backend/app/application/sla.py`.
- Redacted public/admin projections:
  `backend/app/infrastructure/repositories.py` and
  `backend/app/contracts/complaints.py`.
- Durable workflow and silence evidence:
  `backend/app/workflows/complaint_lifecycle.py` and
  `backend/app/application/silence.py`.
- AI boundary and evaluation:
  `backend/app/ai/agno_adapter.py`, `backend/app/infrastructure/ai.py`, and
  `docs/AI_EVALUATION.md`.
- Runtime fail-closed composition:
  `backend/app/runtime.py`, `backend/app/api/main.py`, and
  `docs/architecture/ADR-0001-greenfield-runtime.md`.
- Role and capability authorization:
  `backend/app/application/authorization.py` and
  [`docs/security/CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md).

## 7. Launch gates and owners

These are external actions, not hidden implementation tasks:

- **Legal/security:** complete DigiLocker Requester/API Setu onboarding,
  approve scopes, minimum claims, retention/deletion, DPDP roles, callback
  policy, and provider terms.
- **Platform/security:** provide KMS/secret-manager, network, trusted proxy,
  WAF, shared rate-limit, collector, backup, and deployment controls.
- **Product/privacy:** approve disclosure, closure-proof, public aggregation,
  location precision, retention, citizen appeal, operator-access policies, and
  role assignments against [`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md).
- **AI/platform:** approve model/STT provider terms, region/retention, quotas,
  reviewed multilingual evaluation data, and fallback thresholds.
- **Product/operations:** provide versioned routing/contact/SLA authority before
  outbound messaging. Live operations data and telecom-specific activation are
  intentionally outside the current implementation scope.
- **Finance/platform:** set the monthly spend ceiling and alerts before paid
  production traffic.

## 8. Verification backlog

Before live activation, run and retain evidence for:

1. Authenticated IDOR and privilege-escalation tests across every private and
   operator route.
2. Media replay, malware, parser-fuzz, size, checksum, signed-URL, and
   abandoned-upload cleanup tests.
3. OIDC/DigiLocker negative cases: wrong issuer/audience, expired token,
   nonce/state mismatch, callback replay, claim minimization, and revoked
   verification.
4. Prompt-injection, hallucination, scheme-source, refusal, extraction, and
   weak-reply evaluation by language/dialect.
5. Kafka/Temporal duplicate, outage, replay, clock, and restore drills.
6. Public projection privacy and small-cell re-identification tests.
7. Load/soak tests with budget alarms and provider quota exhaustion.
8. Backup restore, key rotation, deletion/retention, and incident-response
   exercises.

The implementation is not considered production-ready merely because the local
tests pass; each applicable gate requires an environment-specific result and
an owner sign-off.
