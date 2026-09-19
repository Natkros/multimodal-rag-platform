from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import get_settings
from app.services.ingestion import queue as queue_module
from app.services.ingestion.queue import (
    JobQueueNotConfiguredError,
    enqueue_ingestion,
    get_queue,
    run_ingestion_from_disk,
)


def _settings(**overrides):
    return get_settings().model_copy(update=overrides)


@pytest.fixture(autouse=True)
def _clear_queue_caches():
    queue_module._cached_redis_connection.cache_clear()
    queue_module._cached_queue.cache_clear()
    yield
    queue_module._cached_redis_connection.cache_clear()
    queue_module._cached_queue.cache_clear()


def test_get_queue_raises_without_redis_url():
    settings = _settings(redis_url=None)
    with pytest.raises(JobQueueNotConfiguredError):
        get_queue(settings)


def test_get_queue_returns_rq_queue_when_configured():
    settings = _settings(redis_url="redis://localhost:6379/0", job_queue_name="ingestion")
    with patch("app.services.ingestion.queue._cached_redis_connection"):
        queue = get_queue(settings)
    assert queue.name == "ingestion"


def test_enqueue_ingestion_passes_path_not_raw_bytes(tmp_path):
    settings = _settings(redis_url="redis://localhost:6379/0")
    upload_path = tmp_path / "doc.txt"
    upload_path.write_bytes(b"hello world")

    mock_queue = MagicMock()
    with patch("app.services.ingestion.queue.get_queue", return_value=mock_queue):
        enqueue_ingestion("doc-1", "txt", upload_path, "doc.txt", settings, "job-1")

    mock_queue.enqueue.assert_called_once()
    args, kwargs = mock_queue.enqueue.call_args
    assert args[0] is run_ingestion_from_disk
    assert args[1:] == ("doc-1", "txt", str(upload_path), "doc.txt", settings, "job-1")
    assert kwargs["job_timeout"] == settings.job_queue_timeout_seconds


def test_run_ingestion_from_disk_reads_file_and_delegates(tmp_path):
    upload_path = tmp_path / "doc.txt"
    upload_path.write_bytes(b"file contents")
    settings = _settings()

    with patch("app.services.ingestion.pipeline.run_ingestion") as mock_run:
        run_ingestion_from_disk("doc-1", "txt", str(upload_path), "doc.txt", settings, "job-1")

    mock_run.assert_called_once_with("doc-1", "txt", b"file contents", "doc.txt", settings, "job-1")
