from __future__ import annotations

from pathlib import Path

from app.services.retrieval.local_vector_store import LocalVectorStore
from app.services.retrieval.vector_store import VectorRecord


def test_upsert_and_query_returns_nearest(tmp_path: Path):
    store = LocalVectorStore(storage_dir=tmp_path)
    store.upsert(
        [
            VectorRecord("a", [1.0, 0.0], {"document_id": "d1"}),
            VectorRecord("b", [0.0, 1.0], {"document_id": "d1"}),
        ]
    )
    results = store.query([0.9, 0.1], top_k=1)
    assert results[0].vector_id == "a"


def test_query_empty_store_returns_empty(tmp_path: Path):
    store = LocalVectorStore(storage_dir=tmp_path)
    assert store.query([1.0, 0.0], top_k=5) == []


def test_upsert_persists_across_instances(tmp_path: Path):
    store1 = LocalVectorStore(storage_dir=tmp_path)
    store1.upsert([VectorRecord("a", [1.0, 0.0], {"document_id": "d1"})])

    store2 = LocalVectorStore(storage_dir=tmp_path)
    assert store2.count() == 1


def test_delete_by_document_removes_only_matching(tmp_path: Path):
    store = LocalVectorStore(storage_dir=tmp_path)
    store.upsert(
        [
            VectorRecord("a", [1.0, 0.0], {"document_id": "d1"}),
            VectorRecord("b", [0.0, 1.0], {"document_id": "d2"}),
        ]
    )
    store.delete_by_document("d1")
    assert store.count() == 1
    remaining = store.query([0.0, 1.0], top_k=5)
    assert remaining[0].vector_id == "b"


def test_query_respects_metadata_filter(tmp_path: Path):
    store = LocalVectorStore(storage_dir=tmp_path)
    store.upsert(
        [
            VectorRecord("a", [1.0, 0.0], {"document_id": "d1"}),
            VectorRecord("b", [1.0, 0.0], {"document_id": "d2"}),
        ]
    )
    results = store.query([1.0, 0.0], top_k=5, filter={"document_id": "d2"})
    assert [r.vector_id for r in results] == ["b"]
