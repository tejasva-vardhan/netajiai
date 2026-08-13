"""Temporal client adapter for idempotently starting complaint workflows."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from backend.app.contracts.workflow_signals import CitizenResolutionOutcome
from backend.app.workflows.complaint_lifecycle import (
    CitizenConfirmationSignal,
    ComplaintLifecycleWorkflow,
    ComplaintWorkflowInput,
    DepartmentResponseSignal,
    RoutingActivationSignal,
)


class TemporalComplaintWorkflowStarter:
    """Start one workflow per complaint after an outbox consumer commits its work."""

    def __init__(self, client: Client, *, task_queue: str) -> None:
        if not task_queue.strip():
            raise ValueError("Temporal task queue is required")
        self._client = client
        self._task_queue = task_queue

    async def start(self, input: ComplaintWorkflowInput) -> WorkflowHandle:
        workflow_id = f"complaint-{input.complaint_id}"
        try:
            return await self._client.start_workflow(
                ComplaintLifecycleWorkflow.run,
                input,
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        except WorkflowAlreadyStartedError as exc:
            if exc.workflow_id != workflow_id:
                raise
            return self._client.get_workflow_handle(workflow_id, run_id=exc.run_id)


class TemporalComplaintWorkflowSignalSender:
    """Send only typed, idempotent signals to an existing workflow."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def _handle(self, complaint_id: UUID) -> WorkflowHandle:
        return self._client.get_workflow_handle(f"complaint-{complaint_id}")

    async def routing_activation(
        self, complaint_id: UUID, *, signal_id: UUID
    ) -> None:
        await self._handle(complaint_id).signal(
            ComplaintLifecycleWorkflow.routing_activated,
            RoutingActivationSignal(signal_id=str(signal_id)),
        )

    async def department_response(
        self,
        complaint_id: UUID,
        *,
        signal_id: UUID,
        outcome: Literal["fix_reported", "no_resolution"],
        proof_claim_id: UUID | None,
    ) -> None:
        await self._handle(complaint_id).signal(
            ComplaintLifecycleWorkflow.department_response,
            DepartmentResponseSignal(
                signal_id=str(signal_id),
                outcome=outcome,
                proof_claim_id=str(proof_claim_id) if proof_claim_id else None,
            ),
        )

    async def citizen_confirmation(
        self,
        complaint_id: UUID,
        *,
        signal_id: UUID,
        outcome: CitizenResolutionOutcome,
    ) -> None:
        await self._handle(complaint_id).signal(
            ComplaintLifecycleWorkflow.citizen_confirmation,
            CitizenConfirmationSignal(signal_id=str(signal_id), outcome=outcome),
        )
