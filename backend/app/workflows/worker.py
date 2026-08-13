"""Temporal worker construction, kept separate from process startup."""

from __future__ import annotations

from temporalio.client import Client
from temporalio.worker import Worker

from backend.app.workflows.activities import (
    SessionFactory,
    build_silence_activity,
    build_transition_activity,
)
from backend.app.workflows.complaint_lifecycle import ComplaintLifecycleWorkflow


def create_worker(client: Client, session_factory: SessionFactory, *, task_queue: str) -> Worker:
    """Construct a worker without connecting or starting it as a side effect."""

    if not task_queue.strip():
        raise ValueError("Temporal task queue is required")
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[ComplaintLifecycleWorkflow],
        activities=[
            build_transition_activity(session_factory),
            build_silence_activity(session_factory),
        ],
    )
