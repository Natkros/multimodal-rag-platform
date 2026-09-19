from __future__ import annotations

from pathlib import Path

from app.services.retrieval.sparse_index import BM25Index, SparseRecord


def test_upsert_and_query_finds_lexical_match(tmp_path: Path):
    index = BM25Index(storage_dir=tmp_path)
    index.upsert(
        [
            SparseRecord("a", "Acme's cancellation policy allows a 30-day refund.", {"document_id": "d1"}),
            SparseRecord("b", "The weather in Austin was sunny yesterday.", {"document_id": "d1"}),
        ]
    )
    results = index.query("cancellation refund policy", top_k=5)
    assert results
    assert results[0].vector_id == "a"


def test_query_excludes_zero_score_results(tmp_path: Path):
    index = BM25Index(storage_dir=tmp_path)
    index.upsert([SparseRecord("a", "Completely unrelated content about gardening.", {"document_id": "d1"})])
    results = index.query("quantum computing research grants", top_k=5)
    assert results == []


def test_query_empty_index_returns_empty(tmp_path: Path):
    index = BM25Index(storage_dir=tmp_path)
    assert index.query("anything", top_k=5) == []


def test_query_empty_query_text_returns_empty(tmp_path: Path):
    index = BM25Index(storage_dir=tmp_path)
    index.upsert([SparseRecord("a", "Some content here.", {"document_id": "d1"})])
    assert index.query("", top_k=5) == []


def test_upsert_persists_across_instances(tmp_path: Path):
    index1 = BM25Index(storage_dir=tmp_path)
    index1.upsert([SparseRecord("a", "Persisted content about refunds.", {"document_id": "d1"})])

    index2 = BM25Index(storage_dir=tmp_path)
    assert index2.count() == 1
    assert index2.query("refunds", top_k=5)[0].vector_id == "a"


def test_upsert_replaces_existing_id(tmp_path: Path):
    index = BM25Index(storage_dir=tmp_path)
    index.upsert([SparseRecord("a", "Original text about apples.", {"document_id": "d1"})])
    index.upsert([SparseRecord("a", "Updated text about oranges.", {"document_id": "d1"})])

    assert index.count() == 1
    assert index.query("apples", top_k=5) == []
    assert index.query("oranges", top_k=5)


def test_delete_by_document_removes_only_matching(tmp_path: Path):
    index = BM25Index(storage_dir=tmp_path)
    index.upsert(
        [
            SparseRecord("a", "Content from document one.", {"document_id": "d1"}),
            SparseRecord("b", "Content from document two.", {"document_id": "d2"}),
        ]
    )
    index.delete_by_document("d1")
    assert index.count() == 1
    assert index.query("document two", top_k=5)[0].vector_id == "b"


def test_query_respects_metadata_filter(tmp_path: Path):
    index = BM25Index(storage_dir=tmp_path)
    index.upsert(
        [
            SparseRecord("a", "Revenue chart data trending upward.", {"content_type": "image"}),
            SparseRecord("b", "Revenue chart data trending upward.", {"content_type": "table"}),
        ]
    )
    results = index.query("revenue chart data", top_k=5, filter={"content_type": "table"})
    assert [r.vector_id for r in results] == ["b"]
