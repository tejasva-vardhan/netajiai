# AI Neta capability matrix

This is the server-owned authorization baseline for the greenfield API and
operator web surface. An OIDC provider may issue role claims, but it does not
define application permissions. The API maps verified roles through
`backend/app/application/authorization.py` and performs the final capability
check on every protected command or query.

## Role mapping

| Provider role | Aggregate capability | Intended use | Explicit exclusions |
|---|---|---|---|
| `citizen` | Own-resource authorization (not a privileged named capability) | Citizen application; ownership is checked by each application service | No operator reads, routing, lifecycle transitions, scheme approval, or other citizen's records |
| `operator` | `admin.read`, `evidence.review`, `workflow.department_response`, `workflow.routing_activation`, `complaint.transition` | Redacted control tower and operational workflow commands | No scheme/source approval; no unrestricted citizen identity or raw case projection |
| `moderator` | `admin.read`, `evidence.review`, `scheme.review`, `workflow.department_response`, `workflow.routing_activation` | Evidence and grounded-content review | No unrestricted platform configuration; no direct citizen identity access |
| `admin` | All operator and moderator capabilities plus `complaint.transition` | Approved platform administration | Still constrained by redacted contracts, audit, and policy gates |
| `workflow` | `workflow.routing_activation`, `complaint.transition` | Internal Temporal/workflow actor | No human-facing admin reads or content review |
| `viewer` | None in the current API | Reserved for a future read-only projection | Must not be mapped to operator capability by default |

Unknown roles have no capabilities. A subject with multiple verified roles
receives the union of those roles' capabilities; this must be approved during
provider onboarding.

## Endpoint policy

| Capability | Current protected surface | Data/authority boundary |
|---|---|---|
| `admin.read` | Admin overview, complaint summaries, and evidence review queue | Aggregate or redacted projections only; no citizen identity, raw complaint text, or precise location |
| `evidence.review` | Evidence approve/reject decision | Append-only audit, idempotency key, bounded reason code, short-lived preview grant |
| `scheme.review` | Review queue and approve scheme/source records | HTTPS source validation; only explicit approval makes a record answerable |
| `workflow.department_response` | Department-response signal | Raw reply stays private; proof and deterministic workflow rules remain authoritative |
| `workflow.routing_activation` | Routing-activation signal | Resolver owns jurisdiction/contact/SLA facts; request carries no routing data |
| `complaint.transition` | Lifecycle transition command | Domain state machine, closure proof, citizen confirmation, and audit remain authoritative |

## Activation checklist

- Register the provider roles and claim shape (`roles` as a list of strings).
- Map only approved roles to the table above; do not use a global browser secret.
- Verify issuer, audience, signature algorithm, expiry, subject, and key rotation.
- Test every protected route with citizen, operator, moderator, admin, workflow,
  viewer, unknown-role, expired-token, and missing-role principals.
- Review operator assignments, audit retention, logout/session policy, and
  emergency revocation before enabling the production web control tower.
- Keep the matrix versioned with the API contract whenever a capability or
  role changes.
