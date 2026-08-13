"""Transactional event/outbox recording.

Callers must commit the surrounding database transaction. No worker or broker
is contacted from this module, so a crash cannot publish an event without the
corresponding domain commit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from backend.app.domain.complaints import DomainEvent
from backend.app.contracts.events import ComplaintLifecycleEvent
from backend.app.infrastructure.db import ComplaintEventRecord, OutboxMessage


def append_event_and_outbox(
    session: Session,
    event: DomainEvent,
    *,
    topic: str,
    payload: Mapping[str, Any],
) -> tuple[ComplaintEventRecord, OutboxMessage]:
    """Stage an immutable domain event and its delivery record in one transaction."""

    validated_payload: Mapping[str, Any]
    if topic == "complaint.lifecycle.v1":
        validated_payload = ComplaintLifecycleEvent.model_validate(payload).model_dump(
            mode="json", exclude_none=True
        )
    else:
        validated_payload = dict(payload)

    event_record = ComplaintEventRecord(
        event_id=event.event_id,
        complaint_id=event.aggregate_id,
        event_type=event.event_type,
        from_status=event.from_status.value if event.from_status else None,
        to_status=event.to_status.value,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        policy_version=event.policy_version,
        correlation_id=event.correlation_id,
        idempotency_key=event.idempotency_key,
        payload=dict(validated_payload),
        occurred_at=event.occurred_at,
    )
    now = datetime.now(timezone.utc)
    outbox = OutboxMessage(
        event_id=event.event_id,
        topic=topic,
        message_key=str(event.aggregate_id),
        payload=dict(validated_payload),
        available_at=now,
        created_at=now,
    )
    # OutboxMessage has a database foreign key to the event but deliberately
    # does not keep an ORM relationship. Flush the parent explicitly so
    # PostgreSQL cannot order the dependent insert first.
    session.add(event_record)
    session.flush()
    session.add(outbox)
    return event_record, outbox
