# Greenfield backend image

Build from the repository root:

```bash
docker build -f infra/docker/backend.Dockerfile -t ai-neta-backend:dev .
```

The image runs as the non-root `aineta` user and contains the API plus the
worker entrypoints from `pyproject.toml`. The default command is the API;
deployment task definitions may override it with:

- `aineta-outbox-worker`
- `aineta-event-worker`
- `aineta-temporal-worker`
- `aineta-evidence-cleanup-worker`

The image health check calls `/health`, which is a process liveness check. The
default container command uses `backend.app.runtime:app`; staging and
production must provide `COMPOSITION_MODULE` whose `build_adapters(settings)`
returns `RuntimeAdapters` from `backend.app.runtime`.
Use `/ready` for a load-balancer or deployment readiness probe when the API
must be admitted only after its configured database is reachable; it returns
`503` when no database session factory is configured or the bounded `SELECT 1`
check fails.

Run Alembic migrations as an explicit release/deployment job before starting
new API or worker tasks. The image never creates tables at startup and never
contains secrets. Inject configuration through the deployment secret/config
manager.

The runtime composition root is intentionally fail-closed when production
adapters are not supplied. A production ECS task must use the approved
deployment module and inject the real OIDC, DigiLocker Requester, capture
attestation, media inspection, object-store, AI, routing, and Temporal
adapters listed in `backend/README.md`; this image does not turn fixtures into
production behavior.

Runtime dependencies are generated from `pyproject.toml` with `uv lock` and
exported to the hash-checked `requirements.lock`. Update both lock artifacts
with the documented `uv lock`/`uv export` commands and rerun the image build
when a dependency changes; do not use an unconstrained install in a release.

For ECS, repeat the image health check in the task definition and configure
logging, CPU/memory, secrets, IAM, and command overrides there. The AWS ECS
agent only reports health checks specified in the task definition; the image
health check alone is not sufficient for task health.

The parameterized ECS launch profile is in [`../terraform`](../terraform/README.md).
It is disabled by default and requires an immutable image digest, private
network inputs, KMS, scoped Secret Manager ARNs, and budget/security approval
before it can create paid resources.
