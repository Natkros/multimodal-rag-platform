"""End-to-end RQ integration: enqueue a real ingestion job onto a real Redis, run a
real RQ worker against it (burst mode: process what's queued, then exit), and verify
the document actually gets indexed the same way it would via BackgroundTasks.
Skipped when no Redis is reachable (e.g. this project's local dev sandbox, which has
no Redis running) rather than mocked away — CI (.github/workflows/ci.yml) runs a
real `redis:7-alpine` service container specifically so this test executes for real
there. See docs/decisions/0016-phase16-async-job-queue.md.
"""
from __future__ import annotations

import pytest

from app.services.ingestion.queue import enqueue_ingestion


def _redis_reachable(redis_url: str) -> bool:
    try:
        import redis

        redis.Redis.from_url(redis_url, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


REDIS_URL = "redis://localhost:6379/0"
pytestmark = pytest.mark.skipif(
    not _redis_reachable(REDIS_URL),
    reason="No Redis reachable at redis://localhost:6379/0 — this test needs a real queue, not a mock",
)


def test_enqueued_ingestion_job_processed_by_real_worker_indexes_document(test_settings, monkeypatch):
    from app.models.db import Document, get_session_factory, init_db
    from app.repositories.document_repository import DocumentRepository

    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    monkeypatch.setattr(test_settings, "redis_url", REDIS_URL)
    monkeypatch.setattr(test_settings, "job_queue_name", f"test-ingestion-{id(test_settings)}")

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    repo = DocumentRepository(db)
    doc = repo.create(
        Document(filename="queue_test.txt", file_type="txt", file_hash="hash-queue-test", processing_status="UPLOADED")
    )
    document_id = doc.document_id
    db.close()

    upload_path = test_settings.upload_dir / f"{document_id}_queue_test.txt"
    test_settings.upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(b"Acme's revenue grew 20% in 2025. " * 20)

    enqueue_ingestion(document_id, "txt", upload_path, "queue_test.txt", test_settings, "job-queue-test")

    from app.services.ingestion.queue import get_queue

    queue = get_queue(test_settings)
    from rq import Worker

    worker = Worker([queue], connection=queue.connection)
    worker.work(burst=True)

    db = session_factory()
    repo = DocumentRepository(db)
    refreshed = repo.get(document_id)
    assert refreshed.processing_status == "INDEXED"
    assert refreshed.chunk_count >= 1
    db.close()
