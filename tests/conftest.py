from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def test_settings(monkeypatch):
    """Isolate each test in its own temp dir with sqlite + local vector store, and
    reset every process-wide cache (get_settings, embedder, local vector store)."""
    tmp_dir = Path(tempfile.mkdtemp())
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_dir / 'test.db'}")
    monkeypatch.setenv("DATA_DIR", str(tmp_dir))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_dir / "uploads"))
    monkeypatch.setenv("LOCAL_VECTOR_STORE_DIR", str(tmp_dir / "vector_store"))
    monkeypatch.setenv("LOCAL_SPARSE_INDEX_DIR", str(tmp_dir / "sparse_index"))
    monkeypatch.setenv("VECTOR_STORE", "local")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("ENVIRONMENT", "test")

    from app.core.config import get_settings
    from app.services.embeddings.local_embedder import get_local_embedder
    from app.services.query_intelligence import conversation_store
    from app.services.retrieval.factory import _cached_local_store, _cached_sparse_index

    get_settings.cache_clear()
    get_local_embedder.cache_clear()
    _cached_local_store.cache_clear()
    _cached_sparse_index.cache_clear()
    conversation_store.reset_all()

    import app.models.db as db_module

    db_module._engine = None
    db_module._SessionLocal = None

    settings = get_settings()
    yield settings

    get_settings.cache_clear()
    get_local_embedder.cache_clear()
    _cached_local_store.cache_clear()
    _cached_sparse_index.cache_clear()
    conversation_store.reset_all()
    db_module._engine = None
    db_module._SessionLocal = None
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client(test_settings):
    from app.main import create_app
    from app.models.db import init_db

    init_db()
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_docs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "sample_docs"
