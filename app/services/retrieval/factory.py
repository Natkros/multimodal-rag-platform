from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings
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
