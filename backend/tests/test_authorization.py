from backend.app.application.authorization import has_capability
from backend.app.contracts.identity import AuthenticatedPrincipal


def principal(*roles: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal("oidc:test", roles=frozenset(roles))


def test_operator_capabilities_are_explicit_and_do_not_include_scheme_review():
    operator = principal("operator")

    assert has_capability(operator, "admin.read")
    assert has_capability(operator, "evidence.review")
    assert has_capability(operator, "workflow.department_response")
    assert has_capability(operator, "workflow.routing_activation")
    assert has_capability(operator, "complaint.transition")
    assert not has_capability(operator, "scheme.review")


def test_moderator_can_review_grounded_content_but_not_transition_lifecycle():
    moderator = principal("moderator")

    assert has_capability(moderator, "scheme.review")
    assert has_capability(moderator, "evidence.review")
    assert not has_capability(moderator, "complaint.transition")


def test_unknown_and_viewer_roles_fail_closed():
    for role in ("viewer", "unknown", "citizen"):
        assert not has_capability(principal(role), "admin.read")
        assert not has_capability(principal(role), "workflow.routing_activation")


def test_workflow_role_is_not_a_human_admin_role():
    workflow = principal("workflow")

    assert has_capability(workflow, "workflow.routing_activation")
    assert has_capability(workflow, "complaint.transition")
    assert not has_capability(workflow, "admin.read")
