from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from backend.app.contracts.complaints import CreateComplaintRequest
from backend.app.contracts.identity import AuthenticatedPrincipal
from backend.app.application.complaints import TransitionIdempotencyConflict
from backend.app.application.closure import ClosureProofRejected, ClosureProofRequired
from backend.app.domain.complaints import ComplaintAggregate
from backend.app.application.routing import RoutingDecision
from backend.app.infrastructure.closure import SqlAlchemyClosureProofRepository
from backend.app.infrastructure.db import Base, ComplaintRecord
from backend.app.infrastructure.repositories import SqlAlchemyComplaintSubmissionRepository
from backend.app.workflows.activities import build_transition_activity
from backend.app.workflows.complaint_lifecycle import (
    CitizenConfirmationSignal,
    ComplaintLifecycleWorkflow,
    ComplaintWorkflowInput,
    DepartmentResponseSignal,
    RoutingActivationSignal,
    SilenceActivityInput,
    TransitionActivityInput,
)


def _seed_complaint(engine):
    complaint_id = uuid4()
    with Session(engine) as session:
        response = SqlAlchemyComplaintSubmissionRepository(session).persist_received(
            ComplaintAggregate.receive(
                complaint_id,
                actor_type="citizen",
                actor_id="citizen-workflow",
                policy_version="test.v1",
                correlation_id="corr-create",
                idempotency_key="create-workflow",
            ),
            CreateComplaintRequest(
                issue_type="streetlight",
                description="The streetlight is not working.",
                language="en",
                jurisdiction_code="IN-TEST",
                evidence_asset_ids=[uuid4()],
                citizen_confirmation=True,
            ),
            AuthenticatedPrincipal(
                subject_ref="citizen-workflow",
                roles=frozenset({"citizen"}),
                scopes=frozenset(),
                identity_verified=True,
            ),
            RoutingDecision.mapping_in_progress(reason_code="test_fixture"),
        )
    return response.complaint_id


@pytest.mark.asyncio
async def test_transition_activity_uses_domain_service_and_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine)
    factory = sessionmaker(engine)
    apply_transition = build_transition_activity(factory)
    input = TransitionActivityInput(
        complaint_id=complaint_id,
        to_status="verifying",
        idempotency_key="workflow-transition-1",
        correlation_id="workflow:test",
        policy_version="test.v1",
    )

    first = await apply_transition(input)
    second = await apply_transition(input)

    assert first == {"complaint_id": str(complaint_id), "status": "verifying"}
    assert second == first

    with Session(engine) as session:
        record = session.get(ComplaintRecord, complaint_id)
        assert record is not None
        assert record.status == "verifying"
    assert record.version == 2

    with pytest.raises(TransitionIdempotencyConflict, match="belongs to another request"):
        await apply_transition(
            input.__class__(
                complaint_id=complaint_id,
                to_status="needs_clarification",
                idempotency_key=input.idempotency_key,
                correlation_id=input.correlation_id,
                policy_version=input.policy_version,
            )
        )

    await apply_transition(
        TransitionActivityInput(
            complaint_id=complaint_id,
            to_status="needs_clarification",
            idempotency_key="workflow-transition-escalation-metadata",
            correlation_id="workflow:test",
            policy_version="test.v1",
            escalation_level=4,
            public_disclosure_eligible=True,
        )
    )
    with Session(engine) as session:
        record = session.get(ComplaintRecord, complaint_id)
        assert record is not None
        assert record.escalation_level == 4
    assert record.public_disclosure_eligible is True


@pytest.mark.asyncio
async def test_transition_activity_requires_an_accepted_closure_proof_claim():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    complaint_id = _seed_complaint(engine)
    factory = sessionmaker(engine)
    apply_transition = build_transition_activity(factory)

    for number, status in enumerate(
        ("verifying", "routing_review", "sent", "awaiting_response"),
        start=1,
    ):
        await apply_transition(
            TransitionActivityInput(
                complaint_id=complaint_id,
                to_status=status,
                idempotency_key=f"closure-precondition-{number}",
                correlation_id="workflow:closure-proof",
                policy_version="test.v1",
            )
        )

    with pytest.raises(ClosureProofRequired):
        await apply_transition(
            TransitionActivityInput(
                complaint_id=complaint_id,
                to_status="fix_reported",
                idempotency_key="closure-proof-missing",
                correlation_id="workflow:closure-proof",
                policy_version="test.v1",
            )
        )

    missing_claim_id = uuid4()
    with pytest.raises(ClosureProofRejected):
        await apply_transition(
            TransitionActivityInput(
                complaint_id=complaint_id,
                to_status="fix_reported",
                idempotency_key="closure-proof-unknown",
                correlation_id="workflow:closure-proof",
                policy_version="test.v1",
                closure_proof_claim_id=missing_claim_id,
            )
        )

    proof_reference = f"fixture:closure:{complaint_id}:work-order-activity"
    with Session(engine) as session:
        claim = SqlAlchemyClosureProofRepository(session).reserve(
            claim_id=uuid4(),
            complaint_id=complaint_id,
            proof_type="department_reference",
            proof_reference_hash=hashlib.sha256(
                proof_reference.encode("utf-8")
            ).hexdigest(),
            submitted_by="operator:test",
            verifier="fixture-closure-proof-v1",
            idempotency_key="closure-proof-accepted",
            request_fingerprint="a" * 64,
            now=datetime.now(timezone.utc),
        )

    result = await apply_transition(
        TransitionActivityInput(
            complaint_id=complaint_id,
            to_status="fix_reported",
            idempotency_key="closure-proof-accepted-transition",
            correlation_id="workflow:closure-proof",
            policy_version="test.v1",
            closure_proof_claim_id=claim.claim_id,
        )
    )
    assert result["status"] == "fix_reported"


@pytest.mark.asyncio
async def test_temporal_workflow_runs_transitions_and_signals_to_closed():
    transitions: list[str] = []

    @activity.defn(name="apply_complaint_transition")
    async def record_transition(input: TransitionActivityInput) -> dict[str, str]:
        transitions.append(input.to_status)
        return {"complaint_id": str(input.complaint_id), "status": input.to_status}

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="test-complaint-lifecycle",
            workflows=[ComplaintLifecycleWorkflow],
            activities=[record_transition],
        ):
            complaint_id = uuid4()
            handle = await environment.client.start_workflow(
                ComplaintLifecycleWorkflow.run,
                ComplaintWorkflowInput(
                    complaint_id=complaint_id,
                    routing_state="active",
                    response_timeout_seconds=60,
                ),
                id=f"test-complaint-{complaint_id}",
                task_queue="test-complaint-lifecycle",
            )

            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_response":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not reach awaiting_response")

            await handle.signal(
                ComplaintLifecycleWorkflow.department_response,
                DepartmentResponseSignal(
                    signal_id="response-1",
                    outcome="fix_reported",
                    proof_claim_id=str(uuid4()),
                ),
            )
            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_citizen_confirmation":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not reach citizen confirmation")

            await handle.signal(
                ComplaintLifecycleWorkflow.citizen_confirmation,
                CitizenConfirmationSignal(signal_id="confirmation-1", outcome="fully_solved"),
            )
            result = await handle.result()

    assert result.status == "closed"
    assert transitions == [
        "verifying",
        "routing_review",
        "sent",
        "awaiting_response",
        "fix_reported",
        "awaiting_citizen_confirmation",
        "closed",
    ]


@pytest.mark.asyncio
async def test_temporal_workflow_keeps_partial_outcome_in_follow_up():
    transitions: list[str] = []

    @activity.defn(name="apply_complaint_transition")
    async def record_transition(input: TransitionActivityInput) -> dict[str, str]:
        transitions.append(input.to_status)
        return {"complaint_id": str(input.complaint_id), "status": input.to_status}

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="test-complaint-partial-lifecycle",
            workflows=[ComplaintLifecycleWorkflow],
            activities=[record_transition],
        ):
            complaint_id = uuid4()
            handle = await environment.client.start_workflow(
                ComplaintLifecycleWorkflow.run,
                ComplaintWorkflowInput(
                    complaint_id=complaint_id,
                    routing_state="active",
                    response_timeout_seconds=60,
                ),
                id=f"test-partial-complaint-{complaint_id}",
                task_queue="test-complaint-partial-lifecycle",
            )

            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_response":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not reach awaiting_response")

            await handle.signal(
                ComplaintLifecycleWorkflow.department_response,
                DepartmentResponseSignal(
                    signal_id="partial-response-1",
                    outcome="fix_reported",
                    proof_claim_id=str(uuid4()),
                ),
            )
            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_citizen_confirmation":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not reach citizen confirmation")

            await handle.signal(
                ComplaintLifecycleWorkflow.citizen_confirmation,
                CitizenConfirmationSignal(
                    signal_id="partial-confirmation-1", outcome="partially_solved"
                ),
            )
            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_response":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("partial outcome did not reopen follow-up")
            await handle.cancel()

    assert transitions[-2:] == ["reopened", "awaiting_response"]


@pytest.mark.asyncio
async def test_temporal_workflow_keeps_waiting_and_escalates_after_timeout():
    transitions: list[str] = []
    silences: list[SilenceActivityInput] = []

    @activity.defn(name="apply_complaint_transition")
    async def record_transition(input: TransitionActivityInput) -> dict[str, str]:
        transitions.append(input.to_status)
        return {"complaint_id": str(input.complaint_id), "status": input.to_status}

    @activity.defn(name="record_complaint_silence")
    async def record_silence(input: SilenceActivityInput) -> dict[str, str]:
        silences.append(input)
        return {"complaint_id": str(input.complaint_id)}

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="test-complaint-timeout",
            workflows=[ComplaintLifecycleWorkflow],
            activities=[record_transition, record_silence],
        ):
            complaint_id = uuid4()
            handle = await environment.client.start_workflow(
                ComplaintLifecycleWorkflow.run,
                ComplaintWorkflowInput(
                    complaint_id=complaint_id,
                    routing_state="mapping_in_progress",
                    response_timeout_seconds=1,
                ),
                id=f"test-timeout-{complaint_id}",
                task_queue="test-complaint-timeout",
            )
            await handle.signal(
                ComplaintLifecycleWorkflow.routing_activated,
                RoutingActivationSignal(signal_id="routing-timeout-1"),
            )

            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_response":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not reach awaiting_response")

            await environment.sleep(2)
            assert await handle.query(ComplaintLifecycleWorkflow.current_status) == "escalated"

            await handle.signal(
                ComplaintLifecycleWorkflow.department_response,
                DepartmentResponseSignal(
                    signal_id="response-timeout-1",
                    outcome="fix_reported",
                    proof_claim_id=str(uuid4()),
                ),
            )
            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_citizen_confirmation":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not accept a late fix report")

            await handle.signal(
                ComplaintLifecycleWorkflow.citizen_confirmation,
                CitizenConfirmationSignal(signal_id="confirmation-timeout-1", outcome="fully_solved"),
            )
            result = await handle.result()

    assert result.status == "closed"
    assert result.escalation_count == 1
    assert result.escalation_level == 1
    assert result.public_disclosure_eligible is False
    assert "escalated" in transitions
    assert len(silences) == 1
    assert silences[0].reason_code == "department_response_deadline"
    assert silences[0].status == "awaiting_response"
    assert silences[0].escalation_level == 0


@pytest.mark.asyncio
async def test_temporal_workflow_caps_escalation_at_l4_and_marks_disclosure_review():
    escalation_levels: list[int | None] = []
    silence_count = 0

    @activity.defn(name="apply_complaint_transition")
    async def record_transition(input: TransitionActivityInput) -> dict[str, str]:
        if input.to_status == "escalated":
            escalation_levels.append(input.escalation_level)
        return {"complaint_id": str(input.complaint_id), "status": input.to_status}

    @activity.defn(name="record_complaint_silence")
    async def record_silence(input: SilenceActivityInput) -> dict[str, str]:
        nonlocal silence_count
        silence_count += 1
        return {"complaint_id": str(input.complaint_id)}

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="test-complaint-l4",
            workflows=[ComplaintLifecycleWorkflow],
                activities=[record_transition, record_silence],
        ):
            complaint_id = uuid4()
            handle = await environment.client.start_workflow(
                ComplaintLifecycleWorkflow.run,
                ComplaintWorkflowInput(
                    complaint_id=complaint_id,
                    routing_state="active",
                    response_timeout_seconds=1,
                ),
                id=f"test-l4-{complaint_id}",
                task_queue="test-complaint-l4",
            )
            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_response":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not reach awaiting_response")

            await environment.sleep(2)
            for _ in range(3):
                await environment.sleep(31 * 24 * 60 * 60)

            assert escalation_levels[:4] == [1, 2, 3, 4]
            await environment.sleep(31 * 24 * 60 * 60)
            assert all(level is not None and 1 <= level <= 4 for level in escalation_levels)
            assert 5 not in escalation_levels

            await handle.signal(
                ComplaintLifecycleWorkflow.department_response,
                DepartmentResponseSignal(
                    signal_id="response-l4",
                    outcome="fix_reported",
                    proof_claim_id=str(uuid4()),
                ),
            )
            for _ in range(100):
                if await handle.query(ComplaintLifecycleWorkflow.current_status) == "awaiting_citizen_confirmation":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("workflow did not accept the L4 fix report")

            await handle.signal(
                ComplaintLifecycleWorkflow.citizen_confirmation,
                CitizenConfirmationSignal(signal_id="confirmation-l4", outcome="fully_solved"),
            )
            result = await handle.result()

    assert result.escalation_level == 4
    assert result.public_disclosure_eligible is True
    assert silence_count >= 4
