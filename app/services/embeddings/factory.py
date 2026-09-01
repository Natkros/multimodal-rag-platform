from __future__ import annotations

from app.core.config import Settings
from app.services.embeddings.base import Embedder


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "local":
        from app.services.embeddings.local_embedder import get_local_embedder

        return get_local_embedder(settings.embedding_model, settings.embedding_batch_size)
    raise ValueError(f"Unknown embedding_provider: {settings.embedding_provider!r}")
