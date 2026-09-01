"""Dense-only retriever (Phase 1 baseline). Phase 6 adds BM25 + fusion behind the same
`retrieve()` call signature so the API/generation layers don't change."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.embeddings.base import Embedder
from app.services.retrieval.vector_store import VectorStore


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    text: str
    page: int | None
    section: str | None
    score: float


class DenseRetriever:
    def __init__(self, embedder: Embedder, vector_store: VectorStore):
        self.embedder = embedder
        self.vector_store = vector_store

    def retrieve(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> list[RetrievedChunk]:
        query_vector = self.embedder.embed_query(query)
        filter_ = None
        results = self.vector_store.query(query_vector, top_k=top_k, filter=filter_)
        if document_ids:
            allowed = set(document_ids)
            results = [r for r in results if r.metadata.get("document_id") in allowed]
        return [
            RetrievedChunk(
                chunk_id=r.vector_id,
                document_id=r.metadata.get("document_id", ""),
                document_name=r.metadata.get("document_name", ""),
                text=r.metadata.get("text", ""),
                page=r.metadata.get("page"),
                section=r.metadata.get("section"),
                score=r.score,
            )
            for r in results
        ]
