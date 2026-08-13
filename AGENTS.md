# AI Neta — Agent Instructions

## Project intent

AI Neta is a civic-grievance platform. Citizens should be able to describe a civic issue in Hindi, English, or Hinglish, optionally use voice, photo, and map input, receive a routed complaint ID, and track progress. The platform includes citizen-facing experiences, officer/admin workflows, escalation routing, notifications, and transparency features.

This project is being developed with scalable architecture from the beginning. A working demo is an execution priority, not permission to create throwaway architecture. The implementation must remain clean, replaceable, testable, and straightforward to evolve into a production-scale system.

## Non-negotiable engineering principles

### Keep the codebase clean

- Make cohesive changes with clear ownership and boundaries.
- Do not accumulate incremental patches, duplicated logic, compatibility branches, unexplained constants, or temporary hacks in core code.
- Before changing behavior, identify the existing source of truth, data contracts, dependencies, and failure modes.
- Prefer refactoring a boundary or abstraction over adding another special case.
- Keep modules focused. Do not allow the API entrypoint, UI pages, domain logic, database code, and external-provider code to become one mixed layer.
- Remove obsolete code, stale documentation, and dead dependencies when their replacement is complete.
- If a temporary implementation is genuinely necessary for the demo, isolate it behind a well-named interface or adapter, document why it exists, and record the replacement path and exit criteria.

### Build the requested requirements directly

- Do not assume that the product should first receive a deliberately basic version and be “improved later.” Implement the stated requirements directly unless the user explicitly chooses a reduced scope.
- “Working demo first” means prioritizing a complete vertical slice and validating it early; it does not mean weakening the data model, security model, integration boundaries, or future deployment path.
- Do not silently defer a requirement. If something is blocked by credentials, hosting, policy, data, or a product decision, document the exact blocker and the action required from the user.
- Use explicit feature flags, adapters, or configuration when demo and production behavior must differ. Do not fork the business logic into demo and production copies.
- Leave decisions to the user when they are genuinely product or launch-scope decisions. Provide a recommendation, the trade-off, and the concrete action needed, then continue with safe work that does not depend on the decision.

## Current architecture

The repository contains:

- A FastAPI backend under `backend/app`, with `backend.app.runtime:app` as the
  deployed application entrypoint.
- A native Expo citizen app under `apps/mobile/`.
- A Next.js App Router public/operator web surface under `apps/web/`.
- SQLAlchemy persistence and Alembic migrations under `backend/app/` and
  `backend/migrations/`.
- Provider adapters, deterministic test fakes, contracts, security records, and
  deployment profiles under `backend/app/`, `docs/`, and `infra/`.

The former root-level prototype, old `frontend/` app, legacy provider/data
scripts, and probe files have been retired and must not be recreated or used.

When extending this architecture, maintain these conceptual boundaries even if files are later reorganized:

1. **Presentation:** Next.js pages, components, browser state, and API-client code.
2. **API/application:** request validation, authentication, orchestration, and response contracts.
3. **Domain:** complaint lifecycle, routing, escalation, identity, and business rules.
4. **Infrastructure:** PostgreSQL repositories, AI providers, email providers, geocoding, speech-to-text, storage, and queues.
5. **Operations:** configuration, migrations, logging, metrics, deployment, seed data, and runbooks.

Preferred dependency direction:

```text
Frontend → API contracts → Application services → Domain rules
                                      ↓
                            Infrastructure adapters
```

Domain and application code must not depend directly on Groq, Resend, Nominatim, browser APIs, or other vendor SDKs. Put provider-specific behavior behind narrow interfaces/adapters so providers can be replaced, mocked, self-hosted, or scaled independently.

## Scalability-by-design rules

- Treat conversation state, jobs, uploads, rate limits, and caches as replaceable resources. Do not make process memory the only source of truth for user-visible workflows.
- Derive identity from authenticated server-side identity wherever possible. Do not use shared or client-controlled identifiers to isolate users.
- Keep API contracts and persistence schemas explicit and versionable. Avoid returning raw ORM objects from public endpoints.
- Use migrations for production schema evolution. Startup table creation or ad-hoc schema patching may support local development, but must not be the production migration strategy.
- Design notification, transcription, geocoding, and AI calls so they can later move to background jobs, retries, timeouts, and provider fallbacks without changing domain behavior.
- Make idempotency and duplicate handling explicit for complaint registration, uploads, notifications, and webhook-like operations.
- Keep uploads and generated artifacts out of the application process where the deployment model requires durable/shared storage.
- Design authorization around roles and capabilities, not a single global browser-exposed secret.
- Minimize, protect, and limit citizen PII and precise location data. Public transparency data must be intentionally aggregated or redacted.
- Keep observability structured and useful. Do not log raw complaint text, OTPs, tokens, credentials, or unnecessary personal data.

## Frameworks, libraries, and external research

### Verify official documentation

Whenever using or changing a framework, library, SDK, provider API, deployment platform, or protocol:

- Verify the current behavior with the official documentation online before implementation.
- Prefer official documentation, official API references, and primary project repositories over blog posts or copied snippets.
- Check the installed/pinned version and confirm that examples match that version.
- Do not invent configuration keys, lifecycle behavior, APIs, or integration patterns.
- Record important version or compatibility assumptions in the relevant documentation or in the final implementation note.

This applies especially to Next.js, React, FastAPI, Pydantic, SQLAlchemy, PostgreSQL drivers, authentication libraries, Groq, Resend, speech/AI tooling, Leaflet, OpenStreetMap services, hosting platforms, and any replacement selected later.

### Reuse mature solutions

- Before building a subsystem, search for an established framework, library, provider integration, or maintained open-source solution that already solves the problem.
- Prefer solutions that are simple to integrate, actively maintained, well-documented, testable, and compatible with the project’s license and deployment model.
- Evaluate security, privacy, operational complexity, performance, community health, vendor lock-in, and migration cost before adding a dependency.
- Avoid rebuilding authentication, queues, workflow engines, vector/search infrastructure, observability, file storage, and similar capabilities without a strong reason.
- Choose the simplest tool that satisfies the requirements and leaves clean extension points. Favor low integration friction and low unnecessary conceptual overhead over fashionable complexity. The same general principle applies to any framework or agent/AI tool selection; the example of choosing a simpler tool over a more complex alternative is illustrative, not prescriptive.
- Do not add a dependency merely to avoid a small, well-contained function. Do add one when it materially improves correctness, security, maintainability, or integration quality.

### Open-source adaptation is allowed

If an open-source tool does not meet the requirements, it may be adapted substantially, forked, patched, vendored, retrained, fine-tuned, or replaced, provided that:

- Its license, attribution, model terms, and redistribution requirements are respected.
- The changes are tested against the project’s requirements and failure modes.
- The fork or local modifications are clearly documented and reproducible.
- Upstream contribution is considered where practical.
- Training/fine-tuning data, evaluation criteria, model versions, and known limitations are recorded.
- A simpler maintained alternative is reconsidered before committing to a long-lived fork.

## Configuration and user actions

- Never commit real secrets, tokens, passwords, private keys, or personal credentials.
- Keep environment examples synchronized with the actual implementation and deployment requirements.
- Do not leave an empty or implicit user action waiting in the codebase. When user action is required, document:
  - the exact variable, account, provider, URL, file, or decision;
  - why it is needed;
  - how to obtain or configure it;
  - how to verify it; and
  - whether it is safe for local, staging, or production use.
- Use clear `ACTION REQUIRED` sections in setup/deployment documentation and repeat outstanding actions in the final handoff.
- Fail safely when required production configuration is missing. Development fallbacks must not silently become production behavior.
- Keep provider configuration internally consistent. For example, if the implementation uses Resend, document and provision Resend; do not leave misleading SMTP-only instructions.

## Development workflow

Before editing:

- Inspect the repository structure, existing instructions, git status, relevant tests, and nearby implementation.
- Preserve unrelated user changes.
- Identify whether the requested change is a bug fix, requirement implementation, refactor, migration, or infrastructure change.

While editing:

- Make the smallest coherent change that preserves architectural boundaries.
- Reuse existing utilities and components when they are correct.
- Keep validation, error handling, retries, timeouts, and authorization explicit.
- Update documentation and configuration examples when behavior changes.
- Avoid destructive commands and broad rewrites unless explicitly requested.

Before handoff:

- Run the most relevant available checks: formatter, linter, type checker, unit tests, integration tests, build, and/or smoke test.
- Use mocked providers for deterministic tests; do not spend real API credits or send real notifications without explicit authorization.
- Check for secrets, accidental generated files, stale references, and unintended API/schema changes.
- Report what was verified, what could not be verified, why, and the exact next action required.

## Definition of done

A change is complete only when:

- The requested behavior is implemented, not merely scaffolded.
- The change fits the architecture and does not introduce avoidable special cases.
- User identity, authorization, privacy, error handling, and data consistency have been considered.
- Relevant tests or validation exist and pass, or the limitation is clearly documented.
- Configuration, migrations, deployment notes, and user actions are documented where applicable.
- Any temporary adapter or demo-only behavior has an explicit boundary, rationale, and transition path.
- The final handoff states the result, verification status, outstanding risks, and any `ACTION REQUIRED` items.
