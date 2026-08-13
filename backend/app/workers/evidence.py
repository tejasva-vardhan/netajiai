"""Runtime for reclaiming abandoned multipart evidence uploads."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.application.evidence import (
    EvidenceCleanupResult,
    EvidenceUploadCleanupService,
    ObjectStore,
)
from backend.app.config import Settings
from backend.app.infrastructure.evidence_repositories import SqlAlchemyEvidenceMetadataRepository
from backend.app.infrastructure.session import create_session_factory
from backend.app.infrastructure.storage import S3ObjectStore


logger = logging.getLogger(__name__)
SessionFactory = Callable[[], AbstractContextManager[Session]]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


def cleanup_evidence_once(
    settings: Settings,
    session_factory: SessionFactory,
    object_store: ObjectStore,
    *,
    now: datetime | None = None,
) -> EvidenceCleanupResult:
    with session_factory() as session:
        service = EvidenceUploadCleanupService(
            SqlAlchemyEvidenceMetadataRepository(session), object_store
        )
        return service.cleanup_abandoned(
            now=now or datetime.now(timezone.utc),
            max_age_seconds=settings.evidence_cleanup_age_seconds,
            retry_after_seconds=settings.evidence_cleanup_retry_after_seconds,
            limit=settings.evidence_cleanup_batch_size,
        )


async def run_evidence_cleanup_worker(
    settings: Settings,
    session_factory: SessionFactory,
    object_store: ObjectStore,
    *,
    stop_event: asyncio.Event | None = None,
    clock: Clock = lambda: datetime.now(timezone.utc),
    sleeper: Sleeper = asyncio.sleep,
) -> None:
    shutdown = stop_event or asyncio.Event()
    while not shutdown.is_set():
        try:
            result = await asyncio.to_thread(
                cleanup_evidence_once,
                settings,
                session_factory,
                object_store,
                now=clock(),
            )
            logger.info(
                "evidence_cleanup_completed",
                extra={
                    "claimed_count": result.claimed,
                    "cleaned_count": result.cleaned,
                    "failed_count": result.failed,
                },
            )
        except Exception as exc:
            logger.error(
                "evidence_cleanup_failed",
                extra={"error_type": type(exc).__name__},
            )
        await sleeper(settings.evidence_cleanup_interval_seconds)


def main() -> None:
    """Run the production cleanup process without contacting providers on import."""

    settings = Settings.from_env()
    settings.validate_for_worker("evidence_cleanup")
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the evidence cleanup worker")
    if settings.object_storage_provider != "s3":
        raise RuntimeError("OBJECT_STORAGE_PROVIDER=s3 is required for the evidence cleanup worker")

    session_factory = create_session_factory(settings.database_url)
    object_store = S3ObjectStore(
        settings.object_storage_bucket,
        region=settings.object_storage_region,
        endpoint_url=settings.object_storage_endpoint,
        presign_endpoint_url=settings.object_storage_presign_endpoint,
    )
    stop_event = asyncio.Event()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        for signal_name in ("SIGINT", "SIGTERM"):
            signal_number = getattr(signal, signal_name, None)
            if signal_number is not None:
                loop.add_signal_handler(signal_number, stop_event.set)
        await run_evidence_cleanup_worker(
            settings,
            session_factory,
            object_store,
            stop_event=stop_event,
        )

    asyncio.run(run())
