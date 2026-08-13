"""Graceful runtime for the Temporal workflow worker."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import Protocol

from temporalio.client import Client

from backend.app.config import Settings
from backend.app.infrastructure.session import create_session_factory
from backend.app.infrastructure.temporal_client import connect_temporal
from backend.app.workflows.activities import SessionFactory
from backend.app.workflows.worker import create_worker


class TemporalWorkerLike(Protocol):
    async def __aenter__(self) -> "TemporalWorkerLike": ...

    async def __aexit__(
        self, exc_type: type[BaseException] | None, *args: object
    ) -> None: ...

    async def run(self) -> None: ...

    async def shutdown(self) -> None: ...


ClientConnector = Callable[[Settings], Awaitable[Client]]


async def run_temporal_worker(
    settings: Settings,
    session_factory: SessionFactory,
    *,
    stop_event: asyncio.Event | None = None,
    connector: ClientConnector = connect_temporal,
    worker_factory: Callable[[Client, SessionFactory], TemporalWorkerLike]
    | None = None,
) -> None:
    """Connect, run, and gracefully stop a Temporal worker."""

    client = await connector(settings)
    factory = worker_factory or (
        lambda connected_client, sessions: create_worker(
            connected_client,
            sessions,
            task_queue=settings.temporal_task_queue,
        )
    )
    worker = factory(client, session_factory)
    worker_task = asyncio.create_task(worker.run())
    if stop_event is None:
        await worker_task
        return

    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {worker_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if worker_task in done:
            await worker_task
        else:
            await worker.shutdown()
            await worker_task
    finally:
        if not stop_task.done():
            stop_task.cancel()


def main() -> None:
    """Run the production Temporal process; credentials stay in environment/config."""

    settings = Settings.from_env()
    settings.validate_for_worker("temporal")
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the Temporal worker")
    session_factory = create_session_factory(settings.database_url)
    stop_event = asyncio.Event()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, stop_event.set)
        loop.add_signal_handler(signal.SIGTERM, stop_event.set)
        await run_temporal_worker(settings, session_factory, stop_event=stop_event)

    asyncio.run(run())
