"""Graceful runtime for Kafka event consumption."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from backend.app.config import Settings
from backend.app.infrastructure.events import (
    ComplaintLifecycleEventHandler,
    KafkaEventConsumer,
)
from backend.app.infrastructure.temporal import TemporalComplaintWorkflowStarter
from backend.app.infrastructure.temporal_client import connect_temporal


logger = logging.getLogger(__name__)
Sleeper = Callable[[float], Awaitable[None]]


async def run_event_worker(
    consumer: KafkaEventConsumer,
    handler: ComplaintLifecycleEventHandler,
    *,
    poll_interval_seconds: float,
    stop_event: asyncio.Event | None = None,
    sleeper: Sleeper = asyncio.sleep,
) -> None:
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    shutdown = stop_event or asyncio.Event()
    while not shutdown.is_set():
        try:
            handled = await consumer.poll_once(handler)
            logger.info("event_poll_completed", extra={"handled_count": handled})
        except Exception as exc:
            logger.error(
                "event_poll_failed",
                extra={"error_type": type(exc).__name__},
            )
        await sleeper(poll_interval_seconds)


def main() -> None:
    """Run the Kafka-to-Temporal bridge without creating clients on import."""

    settings = Settings.from_env()
    settings.validate_for_worker("events")
    if not settings.kafka_bootstrap_servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is required for the event worker")
    if not settings.temporal_target:
        raise RuntimeError("TEMPORAL_TARGET is required for the event worker")

    try:
        from confluent_kafka import Consumer  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - packaging failure
        raise RuntimeError("confluent-kafka is required for Kafka consumption") from exc

    kafka_client = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": settings.kafka_consumer_group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "client.id": "aineta-events",
        }
    )
    consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers,
        settings.kafka_topic,
        settings.kafka_consumer_group,
        client=kafka_client,
        poll_timeout_seconds=settings.event_poll_interval_seconds,
    )
    stop_event = asyncio.Event()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
        loop.add_signal_handler(signal.SIGTERM, stop_event.set)
        temporal_client = await connect_temporal(settings)
        handler = ComplaintLifecycleEventHandler(
            TemporalComplaintWorkflowStarter(
                temporal_client,
                task_queue=settings.temporal_task_queue,
            )
        )
        try:
            await run_event_worker(
                consumer,
                handler,
                poll_interval_seconds=settings.event_poll_interval_seconds,
                stop_event=stop_event,
            )
        finally:
            kafka_client.close()

    asyncio.run(run())
