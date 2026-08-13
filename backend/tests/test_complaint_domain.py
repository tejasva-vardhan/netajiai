from uuid import uuid4

import pytest

from backend.app.domain.complaints import (
    ComplaintAggregate,
    ComplaintStatus,
    InvalidTransition,
)


def command(
    aggregate: ComplaintAggregate,
    target: ComplaintStatus,
    key: str,
    closure_proof_claim_id=None,
):
    return aggregate.transition(
        target,
        actor_type="system",
        actor_id="test",
        policy_version="policy.test.v1",
        correlation_id="corr-test",
        idempotency_key=key,
        closure_proof_claim_id=closure_proof_claim_id,
    )


def test_complaint_can_follow_verified_submission_path():
    complaint = ComplaintAggregate(uuid4())

    command(complaint, ComplaintStatus.VERIFYING, "verify-1")
    command(complaint, ComplaintStatus.ROUTING_REVIEW, "route-1")
    command(complaint, ComplaintStatus.SENT, "send-1")
    command(complaint, ComplaintStatus.AWAITING_RESPONSE, "await-1")

    assert complaint.status == ComplaintStatus.AWAITING_RESPONSE
    assert complaint.version == 4
    assert [event.to_status for event in complaint.events] == [
        ComplaintStatus.VERIFYING,
        ComplaintStatus.ROUTING_REVIEW,
        ComplaintStatus.SENT,
        ComplaintStatus.AWAITING_RESPONSE,
    ]


def test_same_command_is_idempotent():
    complaint = ComplaintAggregate(uuid4())

    first = command(complaint, ComplaintStatus.VERIFYING, "same-key")
    second = command(complaint, ComplaintStatus.VERIFYING, "same-key")

    assert first is not None
    assert second is None
    assert complaint.version == 1
    assert len(complaint.events) == 1


def test_invalid_transition_is_rejected():
    complaint = ComplaintAggregate(uuid4())

    with pytest.raises(InvalidTransition):
        command(complaint, ComplaintStatus.CLOSED, "close-too-early")


def test_closure_requires_fix_report_and_citizen_confirmation_state():
    complaint = ComplaintAggregate(uuid4())
    command(complaint, ComplaintStatus.VERIFYING, "verify-1")
    command(complaint, ComplaintStatus.ROUTING_REVIEW, "route-1")
    command(complaint, ComplaintStatus.SENT, "send-1")
    command(complaint, ComplaintStatus.AWAITING_RESPONSE, "await-1")
    with pytest.raises(InvalidTransition, match="proof claim"):
        command(complaint, ComplaintStatus.FIX_REPORTED, "proof-missing")
    command(complaint, ComplaintStatus.FIX_REPORTED, "proof-1", uuid4())
    command(complaint, ComplaintStatus.AWAITING_CITIZEN_CONFIRMATION, "confirm-1")
    command(complaint, ComplaintStatus.CLOSED, "closed-1")

    assert complaint.status == ComplaintStatus.CLOSED
