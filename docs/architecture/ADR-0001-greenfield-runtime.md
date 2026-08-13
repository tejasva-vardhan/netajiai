# ADR-0001: Greenfield runtime boundary

**Status:** Accepted for the first implementation slice
**Date:** 2026-08-05

## Decision

Build the new backend under `backend/app` with FastAPI as the HTTP boundary,
pure Python domain modules, provider-neutral application ports, and Agno
behind an AI orchestration adapter. Use Temporal for durable complaint
timers/signals, but keep all business state changes in PostgreSQL through the
application transition service. The retired root-level prototype is not part of
the runtime.

## Why

- FastAPI matches the selected Python application runtime and keeps Agno in the
  same deployable boundary.
- Pure domain modules make complaint lifecycle rules testable without a
  database, model provider, or cloud SDK.
- Provider ports preserve replacement and fake-provider testing paths.
- Separate domain and infrastructure boundaries keep persistence and
  conversational orchestration out of production domain rules.
- Temporal workflows provide durable waiting and retries; replay-safe
  activities call the same deterministic transition service as the HTTP API.

## Consequences

- The greenfield slice is the only supported application boundary.
- The workflow module does not call the database, model provider, or external
  services from workflow code. It uses structured signals and a registered
  transition activity, so workflow history remains small and replay-safe.
- The new API exposes health, evidence upload metadata/completion, and a
  complaint command; production startup still fails closed until its injected
  authentication, storage, capture, and inspection adapters are configured.
- The former root-level prototype was removed after the replacement slice
  covered authentication, complaint commands, evidence handling, routing,
  tracking, and provider-failure behavior. No compatibility branch remains.
