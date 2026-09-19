from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.services.retrieval.local_vector_store import LocalVectorStore
from app.services.retrieval.retriever import HybridRetriever
from app.services.retrieval.sparse_index import BM25Index, SparseRecord
from app.services.retrieval.vector_store import VectorRecord


class FlatEmbedder:
    """Every text embeds to the same vector, so dense search alone can't distinguish
    documents — isolates what BM25 contributes to the fused result."""

    model_name = "flat"
    dimension = 2

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _build_retriever(tmp_path: Path, settings) -> HybridRetriever:
    vector_store = LocalVectorStore(storage_dir=tmp_path / "vectors")
    sparse_index = BM25Index(storage_dir=tmp_path / "sparse")
    embedder = FlatEmbedder()

    records = [
        ("a", "The product code XZ-4471 was recalled in March.", {"document_id": "d1", "content_type": "text"}),
        ("b", "General company policy about vacation days.", {"document_id": "d1", "content_type": "text"}),
        ("c", "Another unrelated paragraph about the office cafeteria.", {"document_id": "d1", "content_type": "text"}),
    ]
    vector_store.upsert(
        [VectorRecord(vid, [1.0, 0.0], {**meta, "text": text, "chunk_id": vid}) for vid, text, meta in records]
    )
    sparse_index.upsert(
        [SparseRecord(vid, text, {**meta, "text": text, "chunk_id": vid}) for vid, text, meta in records]
    )
    return HybridRetriever(embedder=embedder, vector_store=vector_store, sparse_index=sparse_index, settings=settings)


def test_hybrid_surfaces_exact_keyword_match_dense_alone_cannot_distinguish(tmp_path: Path):
    settings = get_settings().model_copy(update={"hybrid_fusion_method": "rrf", "hybrid_candidate_pool": 10})
    retriever = _build_retriever(tmp_path, settings)

    result = retriever.retrieve_with_classification("What happened with product code XZ-4471?", top_k=3)

    # Dense search alone (flat embeddings) can't tell these apart — BM25's exact
    # keyword match on "XZ-4471" is what should surface the right chunk first.
    assert result.chunks[0].chunk_id == "a"


def test_hybrid_respects_content_type_filter_on_both_retrievers(tmp_path: Path):
    settings = get_settings().model_copy(update={"hybrid_fusion_method": "rrf"})
    vector_store = LocalVectorStore(storage_dir=tmp_path / "vectors")
    sparse_index = BM25Index(storage_dir=tmp_path / "sparse")
    embedder = FlatEmbedder()

    vector_store.upsert(
        [
            VectorRecord("img", [1.0, 0.0], {"content_type": "image", "text": "A revenue chart.", "chunk_id": "img"}),
            VectorRecord("tbl", [1.0, 0.0], {"content_type": "table", "text": "A revenue table.", "chunk_id": "tbl"}),
        ]
    )
    sparse_index.upsert(
        [
            SparseRecord("img", "A revenue chart.", {"content_type": "image", "text": "A revenue chart.", "chunk_id": "img"}),
            SparseRecord("tbl", "A revenue table.", {"content_type": "table", "text": "A revenue table.", "chunk_id": "tbl"}),
        ]
    )
    retriever = HybridRetriever(embedder=embedder, vector_store=vector_store, sparse_index=sparse_index, settings=settings)

    result = retriever.retrieve_with_classification("What does the chart show?", top_k=5)
    assert result.matched_content_types == ["image"]
    assert [c.chunk_id for c in result.chunks] == ["img"]


def test_hybrid_retrieve_wrapper_returns_plain_chunk_list(tmp_path: Path):
    settings = get_settings().model_copy(update={"hybrid_fusion_method": "rrf"})
    retriever = _build_retriever(tmp_path, settings)
    chunks = retriever.retrieve("cafeteria", top_k=3)
    assert any(c.chunk_id == "c" for c in chunks)


def test_hybrid_weighted_fusion_method_works_end_to_end(tmp_path: Path):
    settings = get_settings().model_copy(
        update={"hybrid_fusion_method": "weighted", "hybrid_dense_weight": 0.3, "hybrid_sparse_weight": 0.7}
    )
    retriever = _build_retriever(tmp_path, settings)
    result = retriever.retrieve_with_classification("product code XZ-4471 recall", top_k=3)
    assert result.chunks[0].chunk_id == "a"
