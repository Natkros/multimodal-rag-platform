#!/usr/bin/env python
"""Phase 16 RQ worker entrypoint — run alongside the API when
`JOB_QUEUE_BACKEND=rq` to actually process enqueued ingestion jobs. The API process
never processes jobs itself in this mode; it only enqueues them
(app/services/ingestion/queue.py::enqueue_ingestion) and returns immediately.

Usage:
    python workers/ingestion_worker.py

Requires REDIS_URL (and the same DATABASE_URL / vector store config as the API, so
the worker writes to the same database and index the API reads from) — see
docker-compose.yml's `worker` service and docs/decisions/0016-phase16-async-job-queue.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.services.ingestion.queue import JobQueueNotConfiguredError, get_queue


def main() -> None:
    settings = get_settings()
    try:
        queue = get_queue(settings)
    except JobQueueNotConfiguredError as exc:
        print(f"Cannot start worker: {exc}", file=sys.stderr)
        sys.exit(1)

    from rq import Worker

    print(f"Starting RQ worker on queue {settings.job_queue_name!r} ({settings.redis_url})")
    worker = Worker([queue], connection=queue.connection)
    worker.work()


if __name__ == "__main__":
    main()
