# AI Neta

AI Neta is a production-oriented civic-grievance platform for Hindi, English,
and Hinglish citizens. The redesign uses a FastAPI backend, a native Expo
citizen app, a Next.js public/admin web surface, PostgreSQL persistence, Agno
behind a narrow AI port, and Temporal for durable complaint timers and
escalation.

The authoritative architecture and delivery sequence are documented in
[`AI_Neta_Redesign_Plan.md`](AI_Neta_Redesign_Plan.md), with a presentable PDF
at [`AI_Neta_Redesign_Plan.pdf`](AI_Neta_Redesign_Plan.pdf). Repository rules
are in [`AGENTS.md`](AGENTS.md). Launch gates are tracked in
[`docs/ACTION_REQUIRED.md`](docs/ACTION_REQUIRED.md).

## Repository layout

| Path | Role |
| --- | --- |
| `backend/app/` | Greenfield API, application services, domain rules, and provider ports/adapters |
| `apps/mobile/` | Native citizen capture, verification handoff, tracking, and offline retry |
| `apps/web/` | Public receipt tracking, complaint filing, policy-gated transparency, and authenticated operator control tower |
| `backend/migrations/` | Alembic production schema migrations |
| `docs/` | Security, contracts, evaluation, recovery, and architecture records |
| `infra/` | Disabled-by-default container and Terraform launch profiles |

## Local greenfield checks

From the repository root:

```bash
python -m pytest
ruff check backend
mypy backend/app
python scripts/export_contracts.py
```

Run the local API slice with explicit development/test behavior:

```bash
uvicorn backend.app.api.main:app --reload --port 8001
```

Run PostgreSQL migrations only against the intended database:

```bash
cd backend
APP_ENV=development python -m alembic -c alembic.ini upgrade head
```

For the complete local profile, copy/configure the generated root `.env` and
run:

```bash
docker compose up --build
```

This starts the API, web app, workers, PostgreSQL/PostGIS, Redis, Kafka,
MinIO, Keycloak, and Temporal. The exact local actions, seeded accounts,
temporary identity path, Mistral/Deepgram keys, and the intentionally deferred
observability work are in [`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md).

The deployed entrypoint is `backend.app.runtime:app`. Staging and production
must set `COMPOSITION_MODULE` to a deployment-owned module whose
`build_adapters(settings)` returns `backend.app.runtime.RuntimeAdapters`.
Missing or incomplete staging/production adapters cause startup to fail closed.

For the citizen app and web surface, follow:

- [`backend/README.md`](backend/README.md)
- [`apps/mobile/README.md`](apps/mobile/README.md)
- [`apps/web/README.md`](apps/web/README.md)

## Important safety boundaries

- DigiLocker Requester is the planned production verification path; partner
  onboarding, exact endpoint/claim approval, consent, and retention review are
  still required before production activation.
- Operations contacts, live hierarchy/SLA data, and telecom provider
  integrations are intentionally deferred. Synthetic fixtures are not live
  routing or outbound delivery.
- Agno may classify or extract language, but deterministic domain services own
  evidence validity, routing, escalation, disclosure, and closure.
- Raw complaint text, tokens, OTPs, precise location, provider errors, and
  unnecessary identity data must not enter logs or public projections.
- Never commit credentials. Development/test adapters must not be wired into
  staging or production.

## Production activation checklist

Use [`docs/ACTION_REQUIRED.md`](docs/ACTION_REQUIRED.md) and the client/backend
setup READMEs for the exact configuration and verification steps. The short
version is:

1. Complete DigiLocker Requester onboarding and inject the approved transport.
2. Supply real OIDC, PostgreSQL, private object storage, Temporal, Kafka,
   shared rate-limit, observability, capture-attestation, media-inspection,
   speech, closure-proof, and AI adapters through the composition module.
3. Set finance-approved AI/voice caps and provider billing alerts before paid
   traffic; scale from measured usage.
4. Run migrations as a release job, deploy separate API/worker tasks, and
   verify staging failure, retry, authorization, privacy, and recovery cases.

No live provider credentials, operations data, or telecom configuration belongs
in this repository. The retired prototype and its old root-level provider/data
files have been removed; `backend/app`, `apps/mobile`, and `apps/web` are the
only application surfaces.
