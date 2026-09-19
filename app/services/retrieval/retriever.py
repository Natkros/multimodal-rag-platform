"""Retrievers. `DenseRetriever` is the Phase 1 baseline; `HybridRetriever` (Phase 6)
adds BM25 fusion behind the same `retrieve()`/`retrieve_with_classification()` shape
so the API/generation layers, scripts/run_eval.py, and
scripts/compare_chunking_strategies.py don't need to know which one they're using.

Phase 5 adds content-type routing: `retrieve_with_classification()` classifies the
query (app/services/retrieval/query_classifier.py) and, when the wording clearly
points to text/table/image evidence, searches only chunks of that content_type
instead of blending everything by score — the spec's "text retrieval / table
retrieval / image retrieval / hybrid retrieval" modes. `retrieve()` stays a thin
wrapper over it for callers that don't need the classification breakdown.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol

from app.core.config import Settings
from app.services.embeddings.base import Embedder
from app.services.retrieval.fusion import fuse
from app.services.retrieval.query_classifier import classify_query_content_types
from app.services.retrieval.sparse_index import BM25Index
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
    matched_content_types: list[str]  # [] means unrestricted ("hybrid" content-type) search


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


def _apply_document_filter(
    results: list[ScoredVector], document_ids: list[str] | None
) -> list[ScoredVector]:
    if not document_ids:
        return results
    allowed = set(document_ids)
    return [r for r in results if r.metadata.get("document_id") in allowed]


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

        results = _apply_document_filter(results, document_ids)
        return RetrievalResult(
            chunks=[_to_retrieved_chunk(r) for r in results],
            matched_content_types=matched_types,
        )


class Retriever(Protocol):
    def retrieve(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> list[RetrievedChunk]: ...

    def retrieve_with_classification(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> RetrievalResult: ...


class CachingRetriever:
    """Phase 17: wraps any Retriever with a Redis cache keyed on everything that
    affects the result (query text, top_k, document_ids, retrieval mode, embedding
    model) — same decorator pattern as this project's other opt-in wrappers
    (nothing about the wrapped retriever changes). Bounded staleness, not perfect
    invalidation: a cache hit can return results that don't yet reflect a document
    ingested/deleted moments ago, for up to CACHE_TTL_SECONDS. Disclosed explicitly
    in docs/decisions/0017-phase17-caching.md rather than solved with a global
    index-version bump on every mutation, which this project's scale doesn't
    justify the added coupling for."""

    def __init__(self, inner: Retriever, settings: Settings):
        self.inner = inner
        self.settings = settings

    def _cache_key(self, query: str, top_k: int, document_ids: list[str] | None) -> str:
        payload = {
            "query": query,
            "top_k": top_k,
            "document_ids": sorted(document_ids) if document_ids else [],
            "retrieval_mode": self.settings.retrieval_mode,
            "embedding_model": self.settings.embedding_model,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return f"retrieval:{digest}"

    def retrieve(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> list[RetrievedChunk]:
        return self.retrieve_with_classification(query, top_k, document_ids).chunks

    def retrieve_with_classification(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> RetrievalResult:
        from app.services.caching.cache import cache_get, cache_set

        key = self._cache_key(query, top_k, document_ids)
        cached = cache_get(self.settings, key)
        if cached is not None:
            data = json.loads(cached)
            return RetrievalResult(
                chunks=[RetrievedChunk(**c) for c in data["chunks"]],
                matched_content_types=data["matched_content_types"],
            )

        result = self.inner.retrieve_with_classification(query, top_k, document_ids)
        serialized = json.dumps(
            {
                "chunks": [asdict(c) for c in result.chunks],
                "matched_content_types": result.matched_content_types,
            }
        )
        cache_set(self.settings, key, serialized)
        return result


class HybridRetriever:
    """Dense (embedding) + sparse (BM25) retrieval, fused per Phase 6 (ADR 0006).
    Content-type routing (Phase 5) applies to *both* retrievers before fusion: a
    table-directed query runs dense-vs-table and BM25-vs-table, then fuses just
    those, rather than fusing full-corpus results and hoping the right content type
    floats to the top."""

    def __init__(self, embedder: Embedder, vector_store: VectorStore, sparse_index: BM25Index, settings: Settings):
        self.embedder = embedder
        self.vector_store = vector_store
        self.sparse_index = sparse_index
        self.settings = settings

    def retrieve(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> list[RetrievedChunk]:
        return self.retrieve_with_classification(query, top_k, document_ids).chunks

    def retrieve_with_classification(
        self, query: str, top_k: int, document_ids: list[str] | None = None
    ) -> RetrievalResult:
        query_vector = self.embedder.embed_query(query)
        matched_types = sorted(classify_query_content_types(query))
        types_to_search: list[str | None] = matched_types or [None]  # None = unfiltered
        pool = self.settings.hybrid_candidate_pool

        fused_all: list[ScoredVector] = []
        for content_type in types_to_search:
            filter_ = {"content_type": content_type} if content_type else None
            dense_candidates = self.vector_store.query(query_vector, top_k=pool, filter=filter_)
            sparse_candidates = self.sparse_index.query(query, top_k=pool, filter=filter_)
            fused_all.extend(
                fuse(
                    dense_candidates,
                    sparse_candidates,
                    method=self.settings.hybrid_fusion_method,
                    rrf_k=self.settings.hybrid_rrf_k,
                    dense_weight=self.settings.hybrid_dense_weight,
                    sparse_weight=self.settings.hybrid_sparse_weight,
                )
            )
        # Each content_type partition contributes disjoint chunk ids (a chunk has
        # exactly one content_type), so concatenating fused per-type results is safe
        # — no cross-partition id collisions to deduplicate.
        fused_all.sort(key=lambda r: r.score, reverse=True)
        results = _apply_document_filter(fused_all[:top_k], document_ids)

        return RetrievalResult(
            chunks=[_to_retrieved_chunk(r) for r in results],
            matched_content_types=matched_types,
        )
