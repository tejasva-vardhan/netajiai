"""Deterministic Temporal orchestration for a complaint lifecycle.

Temporal owns durable waiting, retries, signals, and timers. It does not own
complaint state: every state change is delegated to the application transition
activity, which persists through the same domain aggregate used by the API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy

from backend.app.contracts.workflow_signals import CitizenResolutionOutcome


WorkflowRoutingState = Literal["mapping_in_progress", "active"]
DepartmentResponseOutcome = Literal["fix_reported", "no_resolution"]
MAX_ESCALATION_LEVEL = 4


@dataclass(frozen=True, slots=True)
class ComplaintWorkflowInput:
    complaint_id: UUID
    routing_state: WorkflowRoutingState = "mapping_in_progress"
    response_timeout_seconds: int = 72 * 60 * 60
    post_escalation_timeout_seconds: int = 30 * 24 * 60 * 60
    policy_version: str = "complaint-policy.v1"
    sla_policy_version: str = "synthetic-sla.v1"


@dataclass(frozen=True, slots=True)
class TransitionActivityInput:
    complaint_id: UUID
    to_status: str
    idempotency_key: str
    correlation_id: str
    policy_version: str
    escalation_level: int | None = None
    public_disclosure_eligible: bool | None = None
    closure_proof_claim_id: UUID | None = None
    citizen_resolution_outcome: CitizenResolutionOutcome | None = None


@dataclass(frozen=True, slots=True)
class SilenceActivityInput:
    complaint_id: UUID
    workflow_id: str
    reason_code: str
    status: str
    deadline_at: datetime
    observed_at: datetime
    escalation_level: int
    escalation_count: int
    policy_version: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class DepartmentResponseSignal:
    signal_id: str
    outcome: DepartmentResponseOutcome
    proof_claim_id: str | None = None


@dataclass(frozen=True, slots=True)
class CitizenConfirmationSignal:
    signal_id: str
    outcome: CitizenResolutionOutcome


@dataclass(frozen=True, slots=True)
class RoutingActivationSignal:
    signal_id: str


@dataclass(frozen=True, slots=True)
class ComplaintWorkflowResult:
    complaint_id: UUID
    status: str
    escalation_count: int
    escalation_level: int
    public_disclosure_eligible: bool


@workflow.defn(name="complaint-lifecycle-v1")
class ComplaintLifecycleWorkflow:
    """Run the stable, policy-controlled portion of a complaint lifecycle."""

    def __init__(self) -> None:
        self._routing_activated = False
        self._department_response: DepartmentResponseOutcome | None = None
        self._department_proof_claim_id: str | None = None
        self._citizen_confirmation: CitizenResolutionOutcome | None = None
        self._current_status = "received"
        self._escalation_count = 0
        self._escalation_level = 0
        self._public_disclosure_eligible = False
        self._seen_signal_ids: set[str] = set()

    @workflow.run
    async def run(self, input: ComplaintWorkflowInput) -> ComplaintWorkflowResult:
        correlation_id = f"workflow:{input.complaint_id}"
        await self._transition(input, "verifying", "received-to-verifying", correlation_id)
        await self._transition(
            input, "routing_review", "verifying-to-routing-review", correlation_id
        )

        if input.routing_state == "mapping_in_progress":
            while not self._routing_activated:
                try:
                    await workflow.wait_condition(
                        lambda: self._routing_activated,
                        timeout=timedelta(days=7),
                        timeout_summary="waiting for jurisdiction routing activation",
                    )
                except TimeoutError:
                    continue
        if not self._routing_activated and input.routing_state != "active":
            raise RuntimeError("Routing was not activated within the workflow policy window")

        await self._transition(input, "sent", "routing-review-to-sent", correlation_id)
        await self._transition(
            input, "awaiting_response", "sent-to-awaiting-response", correlation_id
        )

        while True:
            self._citizen_confirmation = None
            response_deadline = workflow.now() + timedelta(
                seconds=input.response_timeout_seconds
            )
            response_timed_out = False
            try:
                await workflow.wait_condition(
                    lambda: self._department_response is not None,
                    timeout=timedelta(seconds=input.response_timeout_seconds),
                    timeout_summary="waiting for department response",
                )
            except TimeoutError:
                response_timed_out = True
                await self._record_silence(
                    input,
                    reason_code="department_response_deadline",
                    status=self._current_status,
                    deadline_at=response_deadline,
                    escalation_level=self._escalation_level,
                    escalation_count=self._escalation_count,
                )

            if response_timed_out or self._department_response != "fix_reported":
                await self._escalate(
                    input,
                    step="awaiting-response-to-escalated",
                    correlation_id=correlation_id,
                )
                self._department_response = None
                while self._department_response != "fix_reported":
                    response_deadline = workflow.now() + timedelta(
                        seconds=input.post_escalation_timeout_seconds
                    )
                    try:
                        await workflow.wait_condition(
                            lambda: self._department_response == "fix_reported",
                            timeout=timedelta(
                                seconds=input.post_escalation_timeout_seconds
                            ),
                            timeout_summary="waiting for post-escalation fix report",
                        )
                    except TimeoutError:
                        await self._record_silence(
                            input,
                            reason_code="post_escalation_response_deadline",
                            status=self._current_status,
                            deadline_at=response_deadline,
                            escalation_level=self._escalation_level,
                            escalation_count=self._escalation_count,
                        )
                        await self._escalate(
                            input,
                            step="escalation-reminder",
                            correlation_id=correlation_id,
                        )

            await self._transition(
                input,
                "fix_reported",
                f"fix-reported-{self._escalation_count}",
                correlation_id,
                closure_proof_claim_id=UUID(self._department_proof_claim_id),
            )
            await self._transition(
                input,
                "awaiting_citizen_confirmation",
                f"fix-to-citizen-confirmation-{self._escalation_count}",
                correlation_id,
            )
            while self._citizen_confirmation is None:
                try:
                    await workflow.wait_condition(
                        lambda: self._citizen_confirmation is not None,
                        timeout=timedelta(days=30),
                        timeout_summary="waiting for citizen confirmation",
                    )
                except TimeoutError:
                    continue
            if self._citizen_confirmation == "fully_solved":
                await self._transition(
                    input,
                    "closed",
                    f"citizen-confirmation-to-closed-{self._escalation_count}",
                    correlation_id,
                    citizen_resolution_outcome=self._citizen_confirmation,
                )
                return ComplaintWorkflowResult(
                    complaint_id=input.complaint_id,
                    status=self._current_status,
                    escalation_count=self._escalation_count,
                    escalation_level=self._escalation_level,
                    public_disclosure_eligible=self._public_disclosure_eligible,
                )

            await self._transition(
                input,
                "reopened",
                f"citizen-rejection-to-reopened-{self._escalation_count}",
                correlation_id,
                citizen_resolution_outcome=self._citizen_confirmation,
            )
            await self._transition(
                input,
                "awaiting_response",
                f"reopened-to-awaiting-response-{self._escalation_count}",
                correlation_id,
            )
            self._department_response = None

    @workflow.signal(name="routing_activated")
    async def routing_activated(self, signal: RoutingActivationSignal) -> None:
        """Release a workflow waiting for a verified routing decision."""

        if signal.signal_id in self._seen_signal_ids:
            return
        self._seen_signal_ids.add(signal.signal_id)
        self._routing_activated = True

    @workflow.signal(name="department_response")
    async def department_response(self, signal: DepartmentResponseSignal) -> None:
        """Record only a structured outcome; raw officer text stays outside history."""

        if signal.signal_id in self._seen_signal_ids:
            return
        if signal.outcome == "fix_reported" and not signal.proof_claim_id:
            return
        self._seen_signal_ids.add(signal.signal_id)
        if signal.outcome in {"fix_reported", "no_resolution"}:
            self._department_response = signal.outcome
            self._department_proof_claim_id = signal.proof_claim_id

    @workflow.signal(name="citizen_confirmation")
    async def citizen_confirmation(self, signal: CitizenConfirmationSignal) -> None:
        if signal.signal_id in self._seen_signal_ids:
            return
        self._seen_signal_ids.add(signal.signal_id)
        self._citizen_confirmation = signal.outcome

    @workflow.query(name="current_status")
    def current_status(self) -> str:
        return self._current_status

    async def _transition(
        self,
        input: ComplaintWorkflowInput,
        to_status: str,
        step: str,
        correlation_id: str,
        escalation_level: int | None = None,
        public_disclosure_eligible: bool | None = None,
        closure_proof_claim_id: UUID | None = None,
        citizen_resolution_outcome: CitizenResolutionOutcome | None = None,
    ) -> None:
        await workflow.execute_activity(
            "apply_complaint_transition",
            TransitionActivityInput(
                complaint_id=input.complaint_id,
                to_status=to_status,
                idempotency_key=f"{workflow.info().workflow_id}:{step}:v1",
                correlation_id=correlation_id,
                policy_version=input.policy_version,
                escalation_level=escalation_level,
                public_disclosure_eligible=public_disclosure_eligible,
                closure_proof_claim_id=closure_proof_claim_id,
                citizen_resolution_outcome=citizen_resolution_outcome,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=5,
            ),
        )
        self._current_status = to_status

    async def _record_silence(
        self,
        input: ComplaintWorkflowInput,
        *,
        reason_code: str,
        status: str,
        deadline_at: datetime,
        escalation_level: int,
        escalation_count: int,
    ) -> None:
        await workflow.execute_activity(
            "record_complaint_silence",
            SilenceActivityInput(
                complaint_id=input.complaint_id,
                workflow_id=workflow.info().workflow_id,
                reason_code=reason_code,
                status=status,
                deadline_at=deadline_at,
                observed_at=workflow.now(),
                escalation_level=escalation_level,
                escalation_count=escalation_count,
                policy_version=input.sla_policy_version,
                idempotency_key=(
                    f"{workflow.info().workflow_id}:{reason_code}:"
                    f"{escalation_level}:{escalation_count}:v1"
                ),
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=5,
            ),
        )

    async def _escalate(
        self,
        input: ComplaintWorkflowInput,
        *,
        step: str,
        correlation_id: str,
    ) -> None:
        """Advance through L1-L4, then keep L4 durable without inventing L5."""

        self._escalation_level = min(
            self._escalation_level + 1, MAX_ESCALATION_LEVEL
        )
        self._escalation_count += 1
        self._public_disclosure_eligible = (
            self._escalation_level == MAX_ESCALATION_LEVEL
        )
        await self._transition(
            input,
            "escalated",
            f"{step}-l{self._escalation_level}-n{self._escalation_count}",
            correlation_id,
            escalation_level=self._escalation_level,
            public_disclosure_eligible=self._public_disclosure_eligible,
        )
