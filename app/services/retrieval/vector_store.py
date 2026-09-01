"""Vector store abstraction. See docs/decisions/0001-phase1-stack-choices.md.

Everything above this layer (retriever, reranker, generation) talks only to the
`VectorStore` protocol — never to Pinecone or numpy directly — so swapping the backend
(e.g. to Weaviate/Qdrant later) touches only this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class VectorRecord:
    vector_id: str
    values: list[float]
    metadata: dict


@dataclass
class ScoredVector:
    vector_id: str
    score: float
    metadata: dict


class VectorStore(Protocol):
    def upsert(self, records: list[VectorRecord]) -> None: ...

    def query(
        self, vector: list[float], top_k: int, filter: dict | None = None
    ) -> list[ScoredVector]: ...

    def delete_by_document(self, document_id: str) -> None: ...

    def count(self) -> int: ...
