from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError

from backend.app.infrastructure.events import ComplaintLifecycleEventHandler, KafkaEventConsumer
from backend.app.infrastructure.temporal import TemporalComplaintWorkflowStarter
from backend.app.workflows.complaint_lifecycle import ComplaintWorkflowInput
from backend.app.workers.events import run_event_worker


class FakeKafkaMessage:
    def __init__(self, value, *, error=None) -> None:
        self._value = value
        self._error = error

    def value(self):
        return self._value

    def error(self):
        return self._error


class FakeKafkaClient:
    def __init__(self, messages) -> None:
        self.messages = messages
        self.committed: list[FakeKafkaMessage] = []
        self.subscribed: list[list[str]] = []

    def subscribe(self, topics):
        self.subscribed.append(topics)

    def poll(self, timeout):
        del timeout
        return self.messages.pop(0) if self.messages else None

    def commit(self, *, message, asynchronous):
        assert asynchronous is False
        self.committed.append(message)


class RecordingStarter:
    def __init__(self, *, fail: bool = False) -> None:
        self.inputs = []
        self.fail = fail

    async def start(self, input) -> object:
        if self.fail:
            raise RuntimeError("Temporal unavailable")
        self.inputs.append(input)
        return object()


class ExistingWorkflowClient:
    def __init__(self) -> None:
        self.handle_calls: list[tuple[str, str | None]] = []

    async def start_workflow(self, *args, **kwargs):
        del args
        workflow_id = kwargs["id"]
        raise WorkflowAlreadyStartedError(
            workflow_id,
            "complaint-lifecycle-v1",
            run_id="existing-run",
        )

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None):
        self.handle_calls.append((workflow_id, run_id))
        return "existing-workflow-handle"


def _message(*, payload: dict) -> FakeKafkaMessage:
    return FakeKafkaMessage(
        json.dumps(
            {
                "message_id": str(uuid4()),
                "event_id": str(uuid4()),
                "topic": "complaint.lifecycle.v1",
                "message_key": payload.get("complaint_id", "message-key"),
                "payload": payload,
            }
        )
    )


@pytest.mark.asyncio
async def test_temporal_workflow_start_treats_completed_duplicate_as_success():
    client = ExistingWorkflowClient()
    starter = TemporalComplaintWorkflowStarter(client, task_queue="complaint-queue")
    complaint_id = uuid4()

    handle = await starter.start(ComplaintWorkflowInput(complaint_id=complaint_id))

    assert handle == "existing-workflow-handle"
    assert client.handle_calls == [(f"complaint-{complaint_id}", "existing-run")]


@pytest.mark.asyncio
async def test_kafka_consumer_commits_only_successfully_handled_messages():
    complaint_id = uuid4()
    client = FakeKafkaClient(
        [
            _message(
                payload={
                    "status": "received",
                    "complaint_id": str(complaint_id),
                    "execution_zone_state": "active",
                    "sla_policy_version": "synthetic-sla.v1",
                    "response_timeout_seconds": 48 * 60 * 60,
                    "post_escalation_timeout_seconds": 14 * 24 * 60 * 60,
                }
            ),
            _message(
                payload={
                    "status": "received",
                    "complaint_id": str(uuid4()),
                    "execution_zone_state": "invalid",
                }
            ),
        ]
    )
    starter = RecordingStarter()
    consumer = KafkaEventConsumer(
        "kafka:29092", "complaint.lifecycle.v1", "test-group", client=client
    )
    handler = ComplaintLifecycleEventHandler(starter)

    handled = await consumer.poll_once(handler)
    failed = await consumer.poll_once(handler)

    assert handled == 1
    assert failed == 0
    assert len(client.committed) == 1
    assert len(starter.inputs) == 1
    assert starter.inputs[0].complaint_id == complaint_id
    assert starter.inputs[0].routing_state == "active"
    assert starter.inputs[0].response_timeout_seconds == 48 * 60 * 60
    assert starter.inputs[0].post_escalation_timeout_seconds == 14 * 24 * 60 * 60
    assert starter.inputs[0].sla_policy_version == "synthetic-sla.v1"
    assert client.subscribed == [["complaint.lifecycle.v1"]]


@pytest.mark.asyncio
async def test_kafka_consumer_failure_log_excludes_exception_text(caplog):
    client = FakeKafkaClient([FakeKafkaMessage("not-json private citizen description")])
    consumer = KafkaEventConsumer(
        "kafka:29092", "complaint.lifecycle.v1", "test-group", client=client
    )

    with caplog.at_level("ERROR"):
        assert await consumer.poll_once(ComplaintLifecycleEventHandler(RecordingStarter())) == 0

    assert "private citizen description" not in caplog.text
    assert client.committed == []
    assert any(
        getattr(record, "error_type", None) == "ValidationError"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_event_worker_polls_until_shutdown():
    stop_event = asyncio.Event()
    calls = 0
    delays: list[float] = []

    class FakeConsumer:
        async def poll_once(self, handler) -> int:
            nonlocal calls
            calls += 1
            return 0

    async def sleeper(delay: float) -> None:
        delays.append(delay)
        stop_event.set()

    await run_event_worker(
        FakeConsumer(),
        ComplaintLifecycleEventHandler(RecordingStarter()),
        poll_interval_seconds=0.5,
        stop_event=stop_event,
        sleeper=sleeper,
    )

    assert calls == 1
    assert delays == [0.5]
