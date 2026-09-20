"""Configurable fusion of dense + sparse candidate lists (Phase 6).

Two methods, chosen via `HYBRID_FUSION_METHOD`:

- **rrf** (default) — Reciprocal Rank Fusion: `score = sum(1 / (k + rank))` across
  retrievers a document appears in. Rank-based, so it never needs to compare dense
  cosine-similarity scores (roughly [0, 1]) against BM25 scores (unbounded, corpus-
  dependent) on the same scale — which is why RRF is the standard default for
  dense+sparse fusion rather than a naive score sum. The raw formula produces tiny
  scores (~1/k for a top rank, e.g. ~0.016 at k=60) — far below
  `GROUNDING_CONFIDENCE_THRESHOLD`, which was calibrated against dense cosine
  similarity. Left unnormalized, hybrid mode would abstain on every query regardless
  of relevance. `reciprocal_rank_fusion` divides by the theoretical maximum (a chunk
  ranked #1 by every contributing retriever) so fused scores land back in (0, 1] —
  the same scale the confidence gate and API `relevance_score` field already assume,
  without changing RRF's actual ranking (a monotonic rescale).
- **weighted** — linear combination of min-max-normalized scores per retriever
  (`HYBRID_DENSE_WEIGHT` / `HYBRID_SPARSE_WEIGHT`). Needs normalization to be
  meaningful; included because it's more interpretable/tunable than RRF once you
  actually want to weight one retriever over the other, not because it's the
  recommended default.
"""
from __future__ import annotations

from app.services.retrieval.vector_store import ScoredVector


def _normalize(results: list[ScoredVector]) -> dict[str, float]:
    if not results:
        return {}
    scores = [r.score for r in results]
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return dict.fromkeys((r.vector_id for r in results), 1.0)
    return {r.vector_id: (r.score - lo) / (hi - lo) for r in results}


def reciprocal_rank_fusion(
    dense_results: list[ScoredVector], sparse_results: list[ScoredVector], k: int = 60
) -> list[ScoredVector]:
    """Fuse dense and sparse results by rank via RRF, rescaled into (0, 1]. See module docstring."""
    scores: dict[str, float] = {}
    metadata: dict[str, dict] = {}
    n_retrievers = sum(1 for results in (dense_results, sparse_results) if results)

    for rank, r in enumerate(dense_results, start=1):
        scores[r.vector_id] = scores.get(r.vector_id, 0.0) + 1.0 / (k + rank)
        metadata[r.vector_id] = r.metadata
    for rank, r in enumerate(sparse_results, start=1):
        scores[r.vector_id] = scores.get(r.vector_id, 0.0) + 1.0 / (k + rank)
        metadata.setdefault(r.vector_id, r.metadata)

    # Rescale by the theoretical max (rank #1 in every contributing retriever) so
    # fused scores land in (0, 1] — see module docstring for why this matters.
    max_possible = n_retrievers * (1.0 / (k + 1)) if n_retrievers else 1.0
    fused = [
        ScoredVector(vector_id=vid, score=score / max_possible, metadata=metadata[vid])
        for vid, score in scores.items()
    ]
    fused.sort(key=lambda r: r.score, reverse=True)
    return fused


def weighted_fusion(
    dense_results: list[ScoredVector],
    sparse_results: list[ScoredVector],
    dense_weight: float,
    sparse_weight: float,
) -> list[ScoredVector]:
    """Fuse dense and sparse results by a weighted sum of their min-max-normalized scores."""
    dense_norm = _normalize(dense_results)
    sparse_norm = _normalize(sparse_results)
    metadata: dict[str, dict] = {}
    for r in dense_results:
        metadata[r.vector_id] = r.metadata
    for r in sparse_results:
        metadata.setdefault(r.vector_id, r.metadata)

    all_ids = set(dense_norm) | set(sparse_norm)
    scores = {
        vid: dense_weight * dense_norm.get(vid, 0.0) + sparse_weight * sparse_norm.get(vid, 0.0)
        for vid in all_ids
    }
    fused = [ScoredVector(vector_id=vid, score=score, metadata=metadata[vid]) for vid, score in scores.items()]
    fused.sort(key=lambda r: r.score, reverse=True)
    return fused


def fuse(
    dense_results: list[ScoredVector],
    sparse_results: list[ScoredVector],
    method: str,
    rrf_k: int,
    dense_weight: float,
    sparse_weight: float,
) -> list[ScoredVector]:
    """Dispatch to `reciprocal_rank_fusion` or `weighted_fusion` per `HYBRID_FUSION_METHOD`."""
    if method == "rrf":
        return reciprocal_rank_fusion(dense_results, sparse_results, k=rrf_k)
    if method == "weighted":
        return weighted_fusion(dense_results, sparse_results, dense_weight, sparse_weight)
    raise ValueError(f"Unknown hybrid_fusion_method: {method!r}")
