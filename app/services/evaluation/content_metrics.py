"""Content-based (substring) retrieval metrics — used specifically to compare
chunking strategies, where `retrieval_metrics.py`'s exact chunk_id matching doesn't
generalize: two strategies split the same document at different boundaries, so they
never produce the same chunk_id even when both retrieved the right evidence.

Relevance here means "this retrieved chunk's text contains at least one of the
question's expected answer substrings" — chunking-agnostic by construction.

Recall@K is deliberately not computed here: it needs a known total count of relevant
items in the corpus, which content matching can't establish (we don't know how many
chunks *could* contain a matching substring). Hit Rate@K, Precision@K, MRR, and nDCG@K
don't have that requirement and are reported instead — see docs/evaluation.md.
"""
from __future__ import annotations

import math


def is_relevant(chunk_text: str, substrings: list[str]) -> bool:
    if not substrings:
        return False
    lowered = chunk_text.lower()
    return any(s.lower() in lowered for s in substrings if s)


def relevance_vector(retrieved_texts: list[str], substrings: list[str]) -> list[bool]:
    return [is_relevant(text, substrings) for text in retrieved_texts]


def hit_rate_at_k(relevance: list[bool], k: int) -> float:
    return 1.0 if any(relevance[:k]) else 0.0


def precision_at_k(relevance: list[bool], k: int) -> float:
    top_k = relevance[:k]
    if not top_k:
        return 0.0
    return sum(top_k) / len(top_k)


def reciprocal_rank(relevance: list[bool]) -> float:
    for rank, hit in enumerate(relevance, start=1):
        if hit:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevance: list[bool], k: int) -> float:
    top_k = relevance[:k]
    if not any(top_k):
        return 0.0
    dcg = sum(1.0 / math.log2(i + 2) for i, hit in enumerate(top_k) if hit)
    n_relevant = sum(top_k)
    ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(n_relevant))
    return dcg / ideal_dcg if ideal_dcg > 0 else 0.0


def aggregate_content_metrics(
    per_query_retrieved_texts: list[list[str]],
    per_query_substrings: list[list[str]],
    k_values: tuple[int, ...] = (1, 3, 5, 10),
) -> dict:
    n_total = len(per_query_retrieved_texts)
    if n_total == 0:
        return {}

    answerable = [
        (texts, subs)
        for texts, subs in zip(per_query_retrieved_texts, per_query_substrings, strict=True)
        if subs
    ]
    n_answerable = len(answerable)
    result: dict = {
        "n_queries": n_total,
        "n_answerable_queries": n_answerable,
        "n_unanswerable_queries": n_total - n_answerable,
    }
    if n_answerable == 0:
        return result

    relevance_vectors = [relevance_vector(texts, subs) for texts, subs in answerable]

    for k in k_values:
        result[f"hit_rate@{k}"] = sum(hit_rate_at_k(rv, k) for rv in relevance_vectors) / n_answerable
        result[f"precision@{k}"] = sum(precision_at_k(rv, k) for rv in relevance_vectors) / n_answerable
        result[f"ndcg@{k}"] = sum(ndcg_at_k(rv, k) for rv in relevance_vectors) / n_answerable
    result["mrr"] = sum(reciprocal_rank(rv) for rv in relevance_vectors) / n_answerable
    return result
