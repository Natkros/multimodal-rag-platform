"""Deterministic retrieval metrics. See docs/evaluation.md.

All functions take `retrieved_ids: list[str]` (ranked, best first) and
`relevant_ids: set[str]` (the `expected_chunks` for one question) and return a float.
"""
from __future__ import annotations

import math


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(top_k & relevant_ids) / len(relevant_ids)


def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / len(top_k)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    def dcg(ids: list[str]) -> float:
        return sum(
            (1.0 if doc_id in relevant_ids else 0.0) / math.log2(i + 2)
            for i, doc_id in enumerate(ids[:k])
        )

    actual = dcg(retrieved_ids)
    ideal = dcg(list(relevant_ids)[:k]) if relevant_ids else 0.0
    if ideal == 0.0:
        return 0.0
    return actual / ideal


def hit_rate_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    return 1.0 if set(retrieved_ids[:k]) & relevant_ids else 0.0


def aggregate_metrics(
    per_query_retrieved: list[list[str]], per_query_relevant: list[set[str]], k_values: tuple[int, ...] = (1, 3, 5, 10)
) -> dict:
    """Retrieval metrics (Recall/Precision/nDCG/HitRate/MRR) are only meaningful for
    queries that HAVE a ground-truth relevant chunk. Unanswerable queries (empty
    `relevant_ids` — see query_type=unanswerable in the dataset) are counted and
    reported separately as `n_unanswerable_queries`, not silently averaged into
    Recall@K, where an empty ground-truth set would incorrectly read as "0 recall"."""
    n_total = len(per_query_retrieved)
    if n_total == 0:
        return {}

    answerable_pairs = [
        (r, rel) for r, rel in zip(per_query_retrieved, per_query_relevant, strict=True) if rel
    ]
    n_answerable = len(answerable_pairs)
    n_unanswerable = n_total - n_answerable

    result: dict = {
        "n_queries": n_total,
        "n_answerable_queries": n_answerable,
        "n_unanswerable_queries": n_unanswerable,
    }
    if n_answerable == 0:
        return result

    for k in k_values:
        result[f"recall@{k}"] = sum(recall_at_k(r, rel, k) for r, rel in answerable_pairs) / n_answerable
        result[f"precision@{k}"] = (
            sum(precision_at_k(r, rel, k) for r, rel in answerable_pairs) / n_answerable
        )
        result[f"ndcg@{k}"] = sum(ndcg_at_k(r, rel, k) for r, rel in answerable_pairs) / n_answerable
        result[f"hit_rate@{k}"] = (
            sum(hit_rate_at_k(r, rel, k) for r, rel in answerable_pairs) / n_answerable
        )
    result["mrr"] = sum(reciprocal_rank(r, rel) for r, rel in answerable_pairs) / n_answerable
    return result
