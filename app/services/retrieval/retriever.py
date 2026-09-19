"""Dense-only retriever (Phase 1 baseline). Phase 6 adds BM25 + fusion behind the same
`retrieve()` call signature so the API/generation layers don't change.

Phase 5 adds content-type routing: `retrieve_with_classification()` classifies the
query (app/services/retrieval/query_classifier.py) and, when the wording clearly
points to text/table/image evidence, searches only chunks of that content_type
instead of blending everything by score — the spec's "text retrieval / table
retrieval / image retrieval / hybrid retrieval" modes. `retrieve()` stays a thin
wrapper over it for existing callers (scripts/run_eval.py,
scripts/compare_chunking_strategies.py, tests) that don't need the classification
breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.embeddings.base import Embedder
from app.services.retrieval.query_classifier import classify_query_content_types
from app.services.retrieval.vector_store import ScoredVector, VectorStore


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    page: int | None
    section: str | None
    score: float
    content_type: str = "text"


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    matched_content_types: list[str]  # [] means unrestricted ("hybrid") search


def _to_retrieved_chunk(r: ScoredVector) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=r.vector_id,
        document_id=r.metadata.get("document_id", ""),
        document_name=r.metadata.get("document_name", ""),
        text=r.metadata.get("text", ""),
        page=r.metadata.get("page"),
        section=r.metadata.get("section"),
        score=r.score,
        content_type=r.metadata.get("content_type", "text"),
    )


class DenseRetriever:
    def __init__(self, embedder: Embedder, vector_store: VectorStore):
        self.embedder = embedder
        self.vector_store = vector_store

    def retrieve(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> list[RetrievedChunk]:
        return self.retrieve_with_classification(query, top_k, document_ids).chunks

    def retrieve_with_classification(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> RetrievalResult:
        query_vector = self.embedder.embed_query(query)
        matched_types = sorted(classify_query_content_types(query))

        if not matched_types:
            results = self.vector_store.query(query_vector, top_k=top_k, filter=None)
        else:
            # No vector store implements an "in" filter (only equality — see
            # VectorStore.query docs), so a multi-type query runs one filtered search
            # per type and merges by score rather than requiring a richer filter
            # language just for this.
            merged: list[ScoredVector] = []
            for content_type in matched_types:
                merged.extend(
                    self.vector_store.query(
                        query_vector, top_k=top_k, filter={"content_type": content_type}
                    )
                )
            merged.sort(key=lambda r: r.score, reverse=True)
            results = merged[:top_k]

        if document_ids:
            allowed = set(document_ids)
            results = [r for r in results if r.metadata.get("document_id") in allowed]

        return RetrievalResult(
            chunks=[_to_retrieved_chunk(r) for r in results],
            matched_content_types=matched_types,
        )
