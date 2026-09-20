"""BM25 lexical (sparse) retrieval — the second half of Phase 6 hybrid search.

Mirrors `LocalVectorStore`'s shape deliberately (upsert/query/delete_by_document/
count, disk-persisted under a namespace, equality-only metadata filter) so
`HybridRetriever` can treat dense and sparse retrieval symmetrically. There is no
"production" BM25 service in the same sense Pinecone is the production vector store —
the project brief specifies BM25 itself, not a hosted search engine, so this one
implementation is both the dev and the "production" backend.

Rebuilds the whole `BM25Okapi` index on every upsert/delete rather than persisting the
fitted object: `rank_bm25`'s index is just word-count statistics over the corpus, cheap
to rebuild at this project's scale (thousands of chunks, not millions), and rebuilding
from stored raw text avoids pickle/version-compatibility fragility across environments.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.services.retrieval.vector_store import ScoredVector

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class SparseRecord:
    def __init__(self, doc_id: str, text: str, metadata: dict):
        self.doc_id = doc_id
        self.text = text
        self.metadata = metadata


class BM25Index:
    def __init__(self, storage_dir: Path, namespace: str = "default"):
        self.storage_dir = storage_dir
        self.namespace = namespace
        self._data_path = storage_dir / f"{namespace}.bm25.json"
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._texts: list[str] = []
        self._metadata: dict[str, dict] = {}
        self._tokenized_corpus: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._load()

    def _load(self) -> None:
        if self._data_path.exists():
            payload = json.loads(self._data_path.read_text(encoding="utf-8"))
            self._ids = payload["ids"]
            self._texts = payload["texts"]
            self._metadata = payload["metadata"]
        self._rebuild()

    def _save(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._data_path.write_text(
            json.dumps({"ids": self._ids, "texts": self._texts, "metadata": self._metadata}),
            encoding="utf-8",
        )

    def _rebuild(self) -> None:
        if not self._ids:
            self._bm25 = None
            self._tokenized_corpus = []
            return
        self._tokenized_corpus = [_tokenize(t) for t in self._texts]
        self._bm25 = BM25Okapi(self._tokenized_corpus)

    def upsert(self, records: list[SparseRecord]) -> None:
        """Insert or overwrite the given records, rebuild the BM25 index, and persist to disk."""
        if not records:
            return
        with self._lock:
            for record in records:
                if record.doc_id in self._ids:
                    idx = self._ids.index(record.doc_id)
                    self._texts[idx] = record.text
                else:
                    self._ids.append(record.doc_id)
                    self._texts.append(record.text)
                self._metadata[record.doc_id] = record.metadata
            self._rebuild()
            self._save()

    def query(self, query_text: str, top_k: int, filter: dict | None = None) -> list[ScoredVector]:
        """Return the `top_k` BM25 matches for `query_text` that share at least one token with the query."""
        with self._lock:
            if self._bm25 is None or not self._ids:
                return []
            tokenized_query = set(_tokenize(query_text))
            if not tokenized_query:
                return []
            scores = self._bm25.get_scores(list(tokenized_query))

            candidate_indices = range(len(self._ids))
            if filter:
                candidate_indices = [
                    i
                    for i in candidate_indices
                    if all(self._metadata[self._ids[i]].get(k) == v for k, v in filter.items())
                ]

            # Relevance means real lexical term overlap — checked directly against the
            # tokenized document, not by the raw BM25 score's sign. BM25's IDF term
            # can go negative for very common words on a tiny corpus (this project's
            # scale in tests/demos), which would wrongly exclude genuine matches if we
            # filtered on `score > 0` instead.
            scored = [
                (i, scores[i])
                for i in candidate_indices
                if tokenized_query & set(self._tokenized_corpus[i])
            ]
            scored.sort(key=lambda pair: pair[1], reverse=True)

            return [
                ScoredVector(vector_id=self._ids[i], score=float(score), metadata=self._metadata[self._ids[i]])
                for i, score in scored[:top_k]
            ]

    def delete_by_document(self, document_id: str) -> None:
        """Remove every record whose metadata `document_id` matches, rebuild the index, and persist."""
        with self._lock:
            keep = [i for i, doc_id in enumerate(self._ids) if self._metadata.get(doc_id, {}).get("document_id") != document_id]
            self._ids = [self._ids[i] for i in keep]
            self._texts = [self._texts[i] for i in keep]
            self._metadata = {doc_id: self._metadata[doc_id] for doc_id in self._ids}
            self._rebuild()
            self._save()

    def count(self) -> int:
        """Return the total number of records currently indexed."""
        return len(self._ids)
