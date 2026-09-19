"""Phase 17: end-to-end retrieval caching against a real Redis — no mocking. Skipped
when no Redis is reachable (same honest-disclosure pattern as
tests/integration/test_job_queue_rq.py from Phase 16): this dev sandbox has no
Redis running, but CI's redis:7-alpine service container makes this genuinely
execute there. See docs/decisions/0017-phase17-caching.md.
"""
from __future__ import annotations

import time

import pytest

from app.models.db import Document, get_session_factory, init_db
from app.repositories.document_repository import DocumentRepository
from app.services.embeddings.factory import get_embedder
from app.services.ingestion.pipeline import run_ingestion
from app.services.retrieval.factory import get_retriever, get_vector_store


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
    reason="No Redis reachable at redis://localhost:6379/0 — this test needs a real cache, not a mock",
)


def test_cached_retrieval_returns_identical_results_and_is_measurably_faster(test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "redis_url", REDIS_URL)
    monkeypatch.setattr(test_settings, "cache_enabled", True)

    init_db()
    session_factory = get_session_factory()
    db = session_factory()
    repo = DocumentRepository(db)
    doc = repo.create(
        Document(filename="cache_test.txt", file_type="txt", file_hash="hash-cache-test", processing_status="UPLOADED")
    )
    document_id = doc.document_id
    db.close()

    content = ("Acme's revenue grew 20% in 2025 driven by Enterprise tier expansion. " * 20).encode("utf-8")
    run_ingestion(document_id, "txt", content, "cache_test.txt", test_settings)

    embedder = get_embedder(test_settings)
    vector_store = get_vector_store(test_settings, embedder.dimension)
    retriever = get_retriever(test_settings, embedder, vector_store)

    from app.services.retrieval.retriever import CachingRetriever

    assert isinstance(retriever, CachingRetriever)

    # First call: cache miss, does real embedding + vector search.
    start = time.perf_counter()
    first = retriever.retrieve_with_classification("What drove Acme's revenue growth?", top_k=5)
    first_latency_ms = (time.perf_counter() - start) * 1000

    # Second call, identical query: cache hit, should skip embedding + vector search.
    start = time.perf_counter()
    second = retriever.retrieve_with_classification("What drove Acme's revenue growth?", top_k=5)
    second_latency_ms = (time.perf_counter() - start) * 1000

    assert len(first.chunks) == len(second.chunks) >= 1
    assert [c.chunk_id for c in first.chunks] == [c.chunk_id for c in second.chunks]
    assert [c.text for c in first.chunks] == [c.text for c in second.chunks]
    assert second_latency_ms < first_latency_ms
