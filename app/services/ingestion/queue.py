"""Phase 16: an opt-in Redis/RQ-backed job queue, alongside (not replacing) Phase
1's FastAPI `BackgroundTasks` default. `JOB_QUEUE_BACKEND` picks which one runs a
given deployment — `background_tasks` (default, preserves every prior phase's
behavior exactly) or `rq` (a real, persistent, multi-worker queue: survives an API
process restart, and lets ingestion scale across worker processes instead of
running in the request-handling process). See
docs/decisions/0016-phase16-async-job-queue.md for why RQ over Celery, and what
this phase could and couldn't verify without a reachable Redis in this dev
environment.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import Settings


class JobQueueNotConfiguredError(RuntimeError):
    pass


@lru_cache
def _cached_redis_connection(redis_url: str):
    import redis

    return redis.Redis.from_url(redis_url)


@lru_cache
def _cached_queue(redis_url: str, queue_name: str):
    from rq import Queue

    return Queue(queue_name, connection=_cached_redis_connection(redis_url))


def get_queue(settings: Settings):
    """Returns the RQ `Queue` for ingestion jobs. Raises `JobQueueNotConfiguredError`
    if `REDIS_URL` isn't set — the same "fail loud with a clear message, not a
    confusing downstream error" pattern as `LLMNotConfiguredError`
    (app/services/generation/llm_client.py)."""
    if not settings.redis_url:
        raise JobQueueNotConfiguredError("JOB_QUEUE_BACKEND=rq requires REDIS_URL to be set.")
    return _cached_queue(settings.redis_url, settings.job_queue_name)


def run_ingestion_from_disk(
    document_id: str,
    file_type: str,
    upload_path: str,
    filename: str,
    settings: Settings,
    job_id: str,
) -> None:
    """The function an RQ worker actually calls — reads the uploaded file back from
    `upload_dir` (already written there by app/api/routes/documents.py before
    enqueueing) rather than round-tripping the raw file bytes through Redis as a
    pickled job argument, which would be wasteful for anything near
    `MAX_UPLOAD_SIZE_BYTES` and is exactly the kind of thing a real (if modest) queue
    integration should get right rather than defer. Must stay a module-level
    function, not a closure — RQ pickles jobs by import path, not by value."""
    from app.services.ingestion.pipeline import run_ingestion

    raw_bytes = Path(upload_path).read_bytes()
    run_ingestion(document_id, file_type, raw_bytes, filename, settings, job_id)


def enqueue_ingestion(
    document_id: str,
    file_type: str,
    upload_path: Path,
    filename: str,
    settings: Settings,
    job_id: str,
) -> None:
    queue = get_queue(settings)
    queue.enqueue(
        run_ingestion_from_disk,
        document_id,
        file_type,
        str(upload_path),
        filename,
        settings,
        job_id,
        job_timeout=settings.job_queue_timeout_seconds,
    )
