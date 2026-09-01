"""In-process cosine-similarity vector store, persisted to disk.

Default backend for local dev/CI (no external account needed). Not for production
scale — it's a correct, simple reference implementation that satisfies the same
`VectorStore` protocol Pinecone does, so retrieval code is backend-agnostic from day 1.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from app.services.retrieval.vector_store import ScoredVector, VectorRecord


class LocalVectorStore:
    def __init__(self, storage_dir: Path, namespace: str = "default"):
        self.storage_dir = storage_dir
        self.namespace = namespace
        self._vectors_path = storage_dir / f"{namespace}.vectors.npy"
        self._meta_path = storage_dir / f"{namespace}.meta.json"
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._metadata: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._meta_path.exists():
            payload = json.loads(self._meta_path.read_text(encoding="utf-8"))
            self._ids = payload["ids"]
            self._metadata = payload["metadata"]
        if self._vectors_path.exists() and self._ids:
            self._matrix = np.load(self._vectors_path)
        else:
            self._matrix = None

    def _save(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if self._matrix is not None:
            np.save(self._vectors_path, self._matrix)
        self._meta_path.write_text(
            json.dumps({"ids": self._ids, "metadata": self._metadata}), encoding="utf-8"
        )

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        with self._lock:
            for record in records:
                vec = np.array(record.values, dtype=np.float32)
                if record.vector_id in self._ids:
                    idx = self._ids.index(record.vector_id)
                    self._matrix[idx] = vec
                else:
                    self._ids.append(record.vector_id)
                    if self._matrix is None:
                        self._matrix = vec.reshape(1, -1)
                    else:
                        self._matrix = np.vstack([self._matrix, vec.reshape(1, -1)])
                self._metadata[record.vector_id] = record.metadata
            self._save()

    def query(self, vector: list[float], top_k: int, filter: dict | None = None) -> list[ScoredVector]:
        with self._lock:
            if self._matrix is None or len(self._ids) == 0:
                return []
            query_vec = np.array(vector, dtype=np.float32)
            candidate_indices = range(len(self._ids))
            if filter:
                candidate_indices = [
                    i
                    for i in candidate_indices
                    if all(self._metadata[self._ids[i]].get(k) == v for k, v in filter.items())
                ]
            if not candidate_indices:
                return []
            sub_matrix = self._matrix[list(candidate_indices)]
            # Vectors are stored L2-normalized at embed time, so dot product == cosine similarity.
            scores = sub_matrix @ query_vec
            order = np.argsort(-scores)[:top_k]
            results = []
            for rank in order:
                real_idx = list(candidate_indices)[rank]
                vector_id = self._ids[real_idx]
                results.append(
                    ScoredVector(
                        vector_id=vector_id,
                        score=float(scores[rank]),
                        metadata=self._metadata[vector_id],
                    )
                )
            return results

    def delete_by_document(self, document_id: str) -> None:
        with self._lock:
            keep = [
                i
                for i, vid in enumerate(self._ids)
                if self._metadata.get(vid, {}).get("document_id") != document_id
            ]
            self._ids = [self._ids[i] for i in keep]
            self._matrix = self._matrix[keep] if self._matrix is not None and keep else None
            self._metadata = {vid: self._metadata[vid] for vid in self._ids}
            self._save()

    def count(self) -> int:
        return len(self._ids)
