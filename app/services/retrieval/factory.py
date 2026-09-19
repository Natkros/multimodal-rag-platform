from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings
from app.services.retrieval.sparse_index import BM25Index
from app.services.retrieval.vector_store import VectorStore


@lru_cache(maxsize=4)
def _cached_local_store(storage_dir: str, dimension: int) -> VectorStore:
    from pathlib import Path

    from app.services.retrieval.local_vector_store import LocalVectorStore

    return LocalVectorStore(storage_dir=Path(storage_dir))


def get_vector_store(settings: Settings, embedding_dimension: int) -> VectorStore:
    if settings.vector_store == "local":
        return _cached_local_store(str(settings.local_vector_store_dir), embedding_dimension)
    if settings.vector_store == "pinecone":
        if not settings.pinecone_api_key:
            raise ValueError("VECTOR_STORE=pinecone requires PINECONE_API_KEY")
        from app.services.retrieval.pinecone_vector_store import PineconeVectorStore

        return PineconeVectorStore(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index,
            dimension=embedding_dimension,
            cloud=settings.pinecone_cloud,
            region=settings.pinecone_region,
        )
    raise ValueError(f"Unknown vector_store: {settings.vector_store!r}")


@lru_cache(maxsize=4)
def _cached_sparse_index(storage_dir: str) -> BM25Index:
    from pathlib import Path

    return BM25Index(storage_dir=Path(storage_dir))


def get_sparse_index(settings: Settings) -> BM25Index:
    return _cached_sparse_index(str(settings.local_sparse_index_dir))


def get_retriever(settings: Settings, embedder, vector_store: VectorStore):
    """Returns a DenseRetriever or HybridRetriever per RETRIEVAL_MODE, wrapped in a
    CachingRetriever when CACHE_ENABLED=true (Phase 17) — both expose the same
    retrieve()/retrieve_with_classification() shape, so nothing downstream needs to
    know caching is involved. See app/services/retrieval/retriever.py."""
    from app.services.retrieval.retriever import CachingRetriever, DenseRetriever, HybridRetriever

    if settings.retrieval_mode == "dense":
        retriever = DenseRetriever(embedder=embedder, vector_store=vector_store)
    elif settings.retrieval_mode == "hybrid":
        sparse_index = get_sparse_index(settings)
        retriever = HybridRetriever(
            embedder=embedder, vector_store=vector_store, sparse_index=sparse_index, settings=settings
        )
    else:
        raise ValueError(f"Unknown retrieval_mode: {settings.retrieval_mode!r}")

    if settings.cache_enabled:
        return CachingRetriever(retriever, settings)
    return retriever
