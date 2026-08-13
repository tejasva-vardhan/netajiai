"""Server-owned role-to-capability policy.

OIDC supplies role claims, but application code authorizes named capabilities
from this table. Keeping the mapping here prevents endpoint-specific role
sets from drifting as the operator surface grows.
"""

from __future__ import annotations

from typing import Final, Literal

from backend.app.contracts.identity import AuthenticatedPrincipal


Capability = Literal[
    "admin.read",
    "evidence.review",
    "scheme.review",
    "workflow.department_response",
    "workflow.routing_activation",
    "complaint.transition",
]

ROLE_CAPABILITIES: Final[dict[str, frozenset[Capability]]] = {
    "operator": frozenset(
        {
            "admin.read",
            "evidence.review",
            "workflow.department_response",
            "workflow.routing_activation",
            "complaint.transition",
        }
    ),
    "moderator": frozenset(
        {
            "admin.read",
            "evidence.review",
            "scheme.review",
            "workflow.department_response",
            "workflow.routing_activation",
        }
    ),
    "admin": frozenset(
        {
            "admin.read",
            "evidence.review",
            "scheme.review",
            "workflow.department_response",
            "workflow.routing_activation",
            "complaint.transition",
        }
    ),
    "workflow": frozenset(
        {
            "workflow.routing_activation",
            "complaint.transition",
        }
    ),
}


def has_capability(principal: AuthenticatedPrincipal, capability: Capability) -> bool:
    """Return whether a server-verified principal has the named capability."""

    return any(capability in ROLE_CAPABILITIES.get(role, frozenset()) for role in principal.roles)
