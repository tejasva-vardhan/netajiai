# AI Neta local deployment

This is the complete local profile. It runs the same application boundaries as
the deployed shape: the API, web surface, migration job, outbox worker, Kafka
event worker, Temporal workflow worker, evidence cleanup worker, and the
durable local infrastructure services.

## ACTION REQUIRED

The generated, ignored `.env` files are already present for this workspace.
Set these two values in the repository-root `.env` before starting the API:

- `MISTRAL_API_KEY` — a Mistral API key for complaint extraction and
  conversation classification.
- `DEEPGRAM_API_KEY` — a Deepgram API key for verified-audio transcription.

These are the only intentionally blank application values. They cannot be
invented locally because the platform is configured to use the real providers.
Tests use deterministic fakes and do not spend provider credits.

The generated local passwords and HMAC/Fernet keys are for this machine only.
They are ignored by Git and must be regenerated before sharing the environment.

Observability is explicitly deferred for now. The local profile keeps bounded
structured logs but runs with `OTEL_ENABLED=false` and `OTEL_EXPORTER=none`.
Before staging or production, provision an OpenTelemetry collector, enable
OTLP/HTTP, and approve retention, access, dashboards, and alerting.

## Start everything

From the repository root:

```bash
docker compose up --build
```

The first build installs the pinned Python and Node dependencies and runs the
Alembic migration job before starting the API. Useful endpoints are:

- API health: <http://localhost:8001/health>
- API readiness: <http://localhost:8001/ready>
- Web app: <http://localhost:3000>
- Keycloak: <http://localhost:8080>
- MinIO console: <http://localhost:9001>
- Temporal UI: <http://localhost:8233>

Check process state with `docker compose ps`. Stop the stack with
`docker compose down`; that preserves named volumes. Do not use `-v` unless
discarding all local database, Kafka, object-storage, Redis, and Temporal data
is intentional.

## Local accounts and identity

Keycloak imports the `aineta` realm from
[`infra/keycloak/aineta-realm.json`](../infra/keycloak/aineta-realm.json). The
development-only accounts are:

| Account | Password | Capability |
| --- | --- | --- |
| `local-citizen` | `local-citizen` | citizen filing/tracking |
| `test@test.com` | `test123` | requested local citizen test account |
| `local-operator` | `local-operator` | operator workflows |
| `local-admin` | `local-admin` | admin/operator/moderator |

The local realm also allows self-registration from the filing entry flow. New
accounts still need the identity-verification step before they can file a
complaint.

The realm adds the `aineta-api` audience, `roles` claim, and
`identity_verified=true` claim required by the backend. These credentials and
claims are local fixtures, not proof of government identity.

The backend is configured with `IDENTITY_PROVIDER=temporary` and
`DIGILOCKER_MODE=temporary`. The local authorization endpoint completes the
same server-side state/PKCE/callback boundary but uses a short-lived,
HMAC-bound local handoff. It is clearly reported as `temporary` in the API
contract and UI; it must not be represented as DigiLocker verification or
enabled in staging/production.

After government approval, replace the temporary values with the approved
DigiLocker Requester values, set `IDENTITY_PROVIDER=digilocker` and
`DIGILOCKER_MODE=requester`, remove the temporary local route from the
development composition, and run the provider sandbox/replay/expiry tests
before enabling it for real users.

## Client development outside Docker

The web app is already configured in `apps/web/.env.local`. For the native
client:

```bash
cd apps/mobile
npm install
npx expo start
```

`apps/mobile/.env` targets `http://localhost:8001`, which works for a local
simulator. On a physical device, replace the API and Keycloak hostnames with
the development machine's LAN address and register the resulting mobile OIDC
redirect with the local realm. A phone's `localhost` is the phone itself.

The native capture flow remains camera/GPS/microphone based. Browser evidence
uses the signed local capture session and is always sent to review through the
local media inspector; it is not native attestation.

## What is running behind the API

- PostgreSQL/PostGIS stores migrations and all user-visible state.
- Redis supplies the shared local rate-limit store.
- Kafka carries the transactional outbox topic
  `complaint.lifecycle.v1`; offsets are committed only after successful event
  handling.
- MinIO supplies private S3-compatible evidence storage. API presigned URLs
  use `localhost:9000` so browser/mobile clients can upload to the local host,
  while server-side reads use the Docker service name.
- Temporal supplies durable complaint timers and escalation workflows.
- The routing adapter is the bounded synthetic Bhopal/MP fixture until live
  jurisdiction and operations data are approved.

## Verification smoke checks

Run deterministic checks without calling Mistral, Deepgram, or any external
notification provider:

```bash
uv run pytest
uv run ruff check backend
uv run mypy backend/app
npm --prefix apps/web run build
```

Once the stack is running, verify `GET /health` and `GET /ready`, sign in with
the local Keycloak account, open the identity page, and submit a complaint with
native or browser-capture evidence. A complaint should create a PostgreSQL
outbox row, publish to Kafka, and start the corresponding Temporal workflow.
