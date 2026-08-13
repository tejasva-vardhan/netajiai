# Versioned contracts

The greenfield runtime publishes two reviewable contract artifacts:

- [`openapi-v1.json`](openapi-v1.json) — the generated HTTP contract for the
  FastAPI surface. Public API paths are versioned under `/api/v1`; operational
  liveness/readiness endpoints remain outside that versioned namespace.
- [`events/complaint-lifecycle-v1.schema.json`](events/complaint-lifecycle-v1.schema.json)
  — the JSON Schema for the `complaint.lifecycle.v1` queue payload.

Regenerate both artifacts from the repository root with:

```bash
uv run python scripts/export_contracts.py
```

The parity tests compare the committed artifacts with the current Pydantic and
FastAPI definitions. A contract change must therefore update the artifact and
the relevant client/consumer tests in the same change. Do not expose raw ORM
objects, client-controlled identity fields, provider secrets, or unreviewed
complaint text in a public projection.

The queue topic uses at-least-once delivery. Consumers must validate the schema,
deduplicate the downstream effect by a durable envelope/event key, and leave
failed messages for redrive/DLQ handling. The complaint workflow bridge uses
the server-owned complaint workflow ID as that durable effect key; completed
duplicate starts recover the existing run handle. AsyncAPI is intentionally
deferred until a broker consumer catalogue and ownership model exist.
