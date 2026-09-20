"""Phase 26: Maximal Marginal Relevance (MMR) — an advanced-RAG technique not yet
covered by Phases 3/5/6/7/8/9 (chunking, multimodal routing, hybrid fusion,
cross-encoder reranking, query intelligence, context engineering). Where Phase 9's
per-document diversity cap prevents one *document* from crowding out others, MMR
operates one level finer: it can down-rank two chunks from *different* documents
that happen to say nearly the same thing, using embedding similarity rather than
document identity as the diversity signal. See
docs/decisions/0026-phase26-advanced-rag.md for the measured before/after and why
this was chosen over other "advanced RAG" candidates (HyDE, Self-RAG/CRAG) that
need a configured LLM this dev environment doesn't have.
"""
from __future__ import annotations

import math

from app.services.retrieval.retriever import RetrievedChunk


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def select_with_mmr(
    candidates: list[RetrievedChunk],
    candidate_vectors: list[list[float]],
    top_k: int,
    lambda_param: float,
) -> list[RetrievedChunk]:
    """Greedily picks `top_k` candidates maximizing
    `lambda_param * relevance_to_query - (1 - lambda_param) * max_similarity_to_already_selected`.
    `lambda_param=1.0` degenerates to plain relevance-ranked top-k (unchanged
    Phase 1-9 behavior); `lambda_param=0.0` ignores relevance entirely and
    maximizes diversity. Relevance uses each candidate's own retrieval/rerank
    score (already comparable across candidates from the same retrieval call),
    not a re-computed cosine similarity to the query — reusing the score that
    already reflects whatever retrieval mode (dense/hybrid) or reranker produced
    it, rather than second-guessing it with a plain embedding comparison.
    """
    if not candidates:
        return []
    remaining = list(range(len(candidates)))
    selected: list[int] = []

    while remaining and len(selected) < top_k:
        best_idx = None
        best_mmr_score = float("-inf")
        for i in remaining:
            relevance = candidates[i].score
            if selected:
                diversity_penalty = max(
                    _cosine_similarity(candidate_vectors[i], candidate_vectors[j]) for j in selected
                )
            else:
                diversity_penalty = 0.0
            mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity_penalty
            if mmr_score > best_mmr_score:
                best_mmr_score = mmr_score
                best_idx = i
        selected.append(best_idx)
        remaining.remove(best_idx)

    return [candidates[i] for i in selected]


def average_pairwise_similarity(vectors: list[list[float]]) -> float:
    """Diversity metric for evaluation (Phase 26): mean cosine similarity across
    every pair of selected result vectors. Lower means the result set covers more
    distinct content; 0 or 1 result has no pairs, reported as 0.0 (maximally
    "diverse" in the trivial sense of having no redundancy to measure)."""
    if len(vectors) < 2:
        return 0.0
    total = 0.0
    count = 0
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            total += _cosine_similarity(vectors[i], vectors[j])
            count += 1
    return total / count
