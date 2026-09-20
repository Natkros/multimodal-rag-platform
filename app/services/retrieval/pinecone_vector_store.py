"""Pinecone-backed VectorStore. Only imported/instantiated when VECTOR_STORE=pinecone,
so `pinecone` need not be installed/configured for local dev or CI."""
from __future__ import annotations

from app.services.retrieval.vector_store import ScoredVector, VectorRecord


class PineconeVectorStore:
    def __init__(
        self,
        api_key: str,
        index_name: str,
        dimension: int,
        cloud: str = "aws",
        region: str = "us-east-1",
        namespace: str = "default",
    ):
        from pinecone import Pinecone, ServerlessSpec

        self.namespace = namespace
        self._client = Pinecone(api_key=api_key)
        existing = {idx["name"] for idx in self._client.list_indexes()}
        if index_name not in existing:
            self._client.create_index(
                name=index_name,
                dimension=dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud=cloud, region=region),
            )
        self._index = self._client.Index(index_name)

    def upsert(self, records: list[VectorRecord]) -> None:
        """Insert or overwrite the given records in this store's Pinecone namespace."""
        if not records:
            return
        vectors = [(r.vector_id, r.values, r.metadata) for r in records]
        self._index.upsert(vectors=vectors, namespace=self.namespace)

    def query(self, vector: list[float], top_k: int, filter: dict | None = None) -> list[ScoredVector]:
        """Return the `top_k` nearest records to `vector`, optionally restricted by `filter`."""
        response = self._index.query(
            vector=vector, top_k=top_k, filter=filter, namespace=self.namespace, include_metadata=True
        )
        return [
            ScoredVector(vector_id=match["id"], score=match["score"], metadata=match.get("metadata", {}))
            for match in response.get("matches", [])
        ]

    def delete_by_document(self, document_id: str) -> None:
        """Delete every vector whose metadata `document_id` matches."""
        self._index.delete(filter={"document_id": document_id}, namespace=self.namespace)

    def count(self) -> int:
        """Return the total number of vectors stored in this Pinecone index."""
        stats = self._index.describe_index_stats()
        return int(stats.get("total_vector_count", 0))
