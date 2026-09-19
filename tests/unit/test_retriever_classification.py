from __future__ import annotations

from pathlib import Path

from app.services.retrieval.local_vector_store import LocalVectorStore
from app.services.retrieval.retriever import DenseRetriever
from app.services.retrieval.vector_store import VectorRecord


class FakeEmbedder:
    """Every query embeds to the same vector, so ranking is driven purely by which
    records survive the content_type filter, not by real semantic similarity —
    keeps this test about routing, not about embedding quality."""

    model_name = "fake"
    dimension = 2

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _seed_store(tmp_path: Path) -> LocalVectorStore:
    store = LocalVectorStore(storage_dir=tmp_path)
    store.upsert(
        [
            VectorRecord(
                "text-1",
                [1.0, 0.0],
                {
                    "document_id": "d1",
                    "document_name": "doc.txt",
                    "chunk_id": "text-1",
                    "text": "Acme's cancellation policy allows a 30-day refund.",
                    "page": 1,
                    "content_type": "text",
                },
            ),
            VectorRecord(
                "table-1",
                [1.0, 0.0],
                {
                    "document_id": "d1",
                    "document_name": "doc.txt",
                    "chunk_id": "table-1",
                    "text": "| Tier | Requirement |\n|---|---|\n| Tier 1 | SOC 2 |",
                    "page": 2,
                    "content_type": "table",
                },
            ),
            VectorRecord(
                "image-1",
                [1.0, 0.0],
                {
                    "document_id": "d1",
                    "document_name": "doc.txt",
                    "chunk_id": "image-1",
                    "text": "A bar chart showing quarterly revenue trending upward.",
                    "page": 3,
                    "content_type": "image",
                },
            ),
        ]
    )
    return store


def test_image_query_returns_only_image_chunks(tmp_path):
    retriever = DenseRetriever(embedder=FakeEmbedder(), vector_store=_seed_store(tmp_path))
    result = retriever.retrieve_with_classification("What does the chart show?", top_k=5)
    assert result.matched_content_types == ["image"]
    assert [c.chunk_id for c in result.chunks] == ["image-1"]


def test_table_query_returns_only_table_chunks(tmp_path):
    retriever = DenseRetriever(embedder=FakeEmbedder(), vector_store=_seed_store(tmp_path))
    result = retriever.retrieve_with_classification("Compare the two tables.", top_k=5)
    assert result.matched_content_types == ["table"]
    assert [c.chunk_id for c in result.chunks] == ["table-1"]


def test_generic_query_is_unrestricted_and_returns_all_types(tmp_path):
    retriever = DenseRetriever(embedder=FakeEmbedder(), vector_store=_seed_store(tmp_path))
    result = retriever.retrieve_with_classification("What is Acme's cancellation policy?", top_k=5)
    assert result.matched_content_types == []
    assert {c.chunk_id for c in result.chunks} == {"text-1", "table-1", "image-1"}


def test_retrieved_chunk_carries_content_type(tmp_path):
    retriever = DenseRetriever(embedder=FakeEmbedder(), vector_store=_seed_store(tmp_path))
    result = retriever.retrieve_with_classification("Compare the two tables.", top_k=5)
    assert result.chunks[0].content_type == "table"


def test_plain_retrieve_still_works_as_before(tmp_path):
    retriever = DenseRetriever(embedder=FakeEmbedder(), vector_store=_seed_store(tmp_path))
    chunks = retriever.retrieve("What is Acme's cancellation policy?", top_k=5)
    assert {c.chunk_id for c in chunks} == {"text-1", "table-1", "image-1"}


def test_multi_type_match_merges_both_content_types(tmp_path):
    retriever = DenseRetriever(embedder=FakeEmbedder(), vector_store=_seed_store(tmp_path))
    result = retriever.retrieve_with_classification("Does the chart match the table?", top_k=5)
    assert set(result.matched_content_types) == {"image", "table"}
    assert {c.chunk_id for c in result.chunks} == {"image-1", "table-1"}
