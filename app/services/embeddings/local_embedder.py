"""Local, no-API-key embedding model using sentence-transformers.

Loaded lazily and cached process-wide — model load is the expensive part (~1-2s for
MiniLM), so we pay it once per process, not once per request.
"""
from __future__ import annotations

from functools import lru_cache


class LocalEmbedder:
    def __init__(self, model_name: str, batch_size: int = 32):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name)
        self.dimension = self._model.get_embedding_dimension()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts, batch_size=self.batch_size, show_progress_bar=False, normalize_embeddings=True
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode([text], normalize_embeddings=True)[0]
        return vector.tolist()


@lru_cache(maxsize=4)
def get_local_embedder(model_name: str, batch_size: int) -> LocalEmbedder:
    return LocalEmbedder(model_name=model_name, batch_size=batch_size)
