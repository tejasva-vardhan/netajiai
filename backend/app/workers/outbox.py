"""Graceful, bounded runtime for PostgreSQL-outbox dispatch."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.application.outbox import OutboxDispatcher, OutboxPublisher
from backend.app.config import Settings
from backend.app.infrastructure.queues import KafkaOutboxPublisher, SqlAlchemyOutboxRepository
from backend.app.infrastructure.session import create_session_factory


logger = logging.getLogger(__name__)
SessionFactory = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class OutboxBatchResult:
    published: int
    failed: int


def dispatch_outbox_once(
    settings: Settings,
    session_factory: SessionFactory,
    publisher: OutboxPublisher,
    *,
    now: datetime | None = None,
) -> OutboxBatchResult:
    """Dispatch one bounded batch; this function is safe to run in a thread."""

    failures = 0

    def record_failure(error_type: str) -> None:
        nonlocal failures
        del error_type
        failures += 1

    with session_factory() as session:
        dispatcher = OutboxDispatcher(SqlAlchemyOutboxRepository(session), publisher)
        published = dispatcher.dispatch_once(
            limit=settings.outbox_batch_size,
            now=now or datetime.now(timezone.utc),
            on_failure=record_failure,
        )
    return OutboxBatchResult(published=published, failed=failures)


async def run_outbox_worker(
    settings: Settings,
    session_factory: SessionFactory,
    publisher: OutboxPublisher,
    *,
    stop_event: asyncio.Event | None = None,
    clock: Clock = lambda: datetime.now(timezone.utc),
    sleeper: Sleeper = asyncio.sleep,
) -> None:
    """Poll until shutdown, isolating blocking database/provider calls in a thread."""

    shutdown = stop_event or asyncio.Event()
    while not shutdown.is_set():
        try:
            result = await asyncio.to_thread(
                dispatch_outbox_once,
                settings,
                session_factory,
                publisher,
                now=clock(),
            )
        except Exception as exc:
            logger.error(
                "outbox_dispatch_failed",
                extra={"error_type": type(exc).__name__},
            )
            await sleeper(settings.outbox_error_backoff_seconds)
            continue

        logger.info(
            "outbox_dispatch_completed",
            extra={
                "published_count": result.published,
                "failed_count": result.failed,
            },
        )
        await sleeper(
            settings.outbox_error_backoff_seconds
            if result.failed
            else settings.outbox_poll_interval_seconds
        )


def main() -> None:
    """Run the production outbox process; no provider is contacted on import."""

    settings = Settings.from_env()
    settings.validate_for_worker("outbox")
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the outbox worker")
    if not settings.kafka_bootstrap_servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is required for the outbox worker")

    session_factory = create_session_factory(settings.database_url)
    publisher = KafkaOutboxPublisher(settings.kafka_bootstrap_servers)
    stop_event = asyncio.Event()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        for signal_name in ("SIGINT", "SIGTERM"):
            signal_number = getattr(signal, signal_name, None)
            if signal_number is not None:
                loop.add_signal_handler(signal_number, stop_event.set)
        await run_outbox_worker(settings, session_factory, publisher, stop_event=stop_event)

    asyncio.run(run())
