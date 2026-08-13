"""Kafka and PostgreSQL-outbox adapters."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.outbox import OutboxItem, OutboxRepository, OutboxPublisher
from backend.app.infrastructure.db import OutboxMessage


class SqlAlchemyOutboxRepository(OutboxRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def claim_ready(self, *, limit: int, now: datetime) -> list[OutboxItem]:
        records = list(
            self._session.scalars(
                select(OutboxMessage)
                .where(
                    OutboxMessage.published_at.is_(None),
                    OutboxMessage.available_at <= now,
                )
                .order_by(OutboxMessage.available_at, OutboxMessage.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for record in records:
            record.attempts += 1
        self._session.commit()
        return [
            OutboxItem(
                message_id=record.id,
                event_id=record.event_id,
                topic=record.topic,
                message_key=record.message_key,
                payload=dict(record.payload),
                attempts=record.attempts,
            )
            for record in records
        ]

    def mark_published(self, message_id: UUID, *, published_at: datetime) -> None:
        record = self._session.get(OutboxMessage, message_id)
        if record is None or record.published_at is not None:
            return
        record.published_at = published_at
        self._session.commit()

    def mark_failed(self, message_id: UUID, *, error: str) -> None:
        record = self._session.get(OutboxMessage, message_id)
        if record is None or record.published_at is not None:
            return
        record.last_error = error[:255]
        record.available_at = datetime.now(timezone.utc)
        self._session.commit()


class KafkaOutboxPublisher(OutboxPublisher):
    """Publish committed outbox records to Kafka with synchronous delivery."""

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        client: Any | None = None,
    ) -> None:
        if not bootstrap_servers.strip():
            raise ValueError("Kafka bootstrap servers are required")
        if client is None:
            try:
                from confluent_kafka import Producer  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - packaging failure
                raise RuntimeError("confluent-kafka is required for Kafka publishing") from exc
            client = Producer(
                {
                    "bootstrap.servers": bootstrap_servers,
                    "client.id": "aineta-outbox",
                    "enable.idempotence": True,
                    "acks": "all",
                }
            )
        self._client = client

    def publish(self, item: OutboxItem) -> None:
        body = json.dumps(
            {
                "message_id": str(item.message_id),
                "event_id": str(item.event_id),
                "topic": item.topic,
                "message_key": item.message_key,
                "payload": item.payload,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        self._client.produce(
            topic=item.topic,
            key=str(item.message_key),
            value=body,
            headers=[("topic", item.topic.encode("utf-8"))],
        )
        self._client.flush()
