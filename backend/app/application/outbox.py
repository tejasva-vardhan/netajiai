"""Application-level transactional-outbox dispatch policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OutboxItem:
    message_id: UUID
    event_id: UUID
    topic: str
    message_key: str
    payload: dict
    attempts: int


class OutboxRepository(Protocol):
    def claim_ready(self, *, limit: int, now: datetime) -> list[OutboxItem]: ...

    def mark_published(self, message_id: UUID, *, published_at: datetime) -> None: ...

    def mark_failed(self, message_id: UUID, *, error: str) -> None: ...


class OutboxPublisher(Protocol):
    def publish(self, item: OutboxItem) -> None: ...


class OutboxDispatcher:
    """Dispatch a bounded batch; a crash may duplicate but never loses a row."""

    def __init__(self, repository: OutboxRepository, publisher: OutboxPublisher) -> None:
        self._repository = repository
        self._publisher = publisher

    def dispatch_once(
        self,
        *,
        limit: int,
        now: datetime,
        on_failure: Callable[[str], None] | None = None,
    ) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        items = self._repository.claim_ready(limit=limit, now=now)
        published = 0
        for item in items:
            try:
                self._publisher.publish(item)
            except Exception as exc:
                # Do not include payloads or complaint text in error state.
                self._repository.mark_failed(
                    item.message_id, error=type(exc).__name__[:255]
                )
                if on_failure is not None:
                    on_failure(type(exc).__name__)
                continue
            self._repository.mark_published(item.message_id, published_at=now)
            published += 1
        return published
