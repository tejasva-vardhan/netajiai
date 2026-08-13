"""Kafka event-consumption and Temporal workflow-start adapters."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from backend.app.contracts.events import ComplaintLifecycleEvent, QueueEnvelope
from backend.app.domain.complaints import ComplaintStatus
from backend.app.workflows.complaint_lifecycle import (
    ComplaintWorkflowInput,
    WorkflowRoutingState,
)


logger = logging.getLogger(__name__)


class QueueEventHandler(Protocol):
    async def handle(self, envelope: QueueEnvelope) -> None: ...


class ComplaintWorkflowStarter(Protocol):
    async def start(self, input: ComplaintWorkflowInput) -> object: ...


class KafkaEventConsumer:
    """Consume Kafka records and commit offsets only after successful handling."""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        *,
        client: Any,
        poll_timeout_seconds: float = 1.0,
    ) -> None:
        if not bootstrap_servers.strip():
            raise ValueError("Kafka bootstrap servers are required")
        if not topic.strip():
            raise ValueError("Kafka topic is required")
        if not group_id.strip():
            raise ValueError("Kafka consumer group is required")
        if poll_timeout_seconds <= 0:
            raise ValueError("poll_timeout_seconds must be positive")
        self._topic = topic
        self._client = client
        self._poll_timeout_seconds = poll_timeout_seconds
        self._client.subscribe([topic])

    async def poll_once(self, handler: QueueEventHandler) -> int:
        message = await asyncio.to_thread(self._client.poll, self._poll_timeout_seconds)
        if message is None:
            return 0
        error = message.error()
        if error is not None:
            logger.error("kafka_event_poll_failed", extra={"error_type": type(error).__name__})
            return 0
        body = message.value()
        if not isinstance(body, (bytes, bytearray, str)):
            logger.error("kafka_message_missing_required_fields")
            return 0
        try:
            envelope = QueueEnvelope.model_validate_json(body)
            await handler.handle(envelope)
        except Exception as exc:
            # Do not commit failed records; Kafka will redeliver them.
            logger.error(
                "kafka_event_handling_failed",
                extra={"error_type": type(exc).__name__},
            )
            return 0
        await asyncio.to_thread(self._client.commit, message=message, asynchronous=False)
        return 1


class ComplaintLifecycleEventHandler:
    """Translate only the creation event into a durable workflow start."""

    def __init__(self, starter: ComplaintWorkflowStarter) -> None:
        self._starter = starter

    async def handle(self, envelope: QueueEnvelope) -> None:
        if envelope.topic != "complaint.lifecycle.v1":
            return
        event = ComplaintLifecycleEvent.model_validate(envelope.payload)
        if event.status != ComplaintStatus.RECEIVED:
            return
        if event.execution_zone_state not in {"active", "mapping_in_progress"}:
            raise ValueError("complaint.received payload has invalid routing state")
        routing_state_value: WorkflowRoutingState = (
            "active"
            if event.execution_zone_state == "active"
            else "mapping_in_progress"
        )
        await self._starter.start(
            ComplaintWorkflowInput(
                complaint_id=event.complaint_id,
                routing_state=routing_state_value,
                response_timeout_seconds=(
                    event.response_timeout_seconds or 72 * 60 * 60
                ),
                post_escalation_timeout_seconds=(
                    event.post_escalation_timeout_seconds or 30 * 24 * 60 * 60
                ),
                sla_policy_version=event.sla_policy_version or "synthetic-sla.v1",
            )
        )
