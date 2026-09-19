from __future__ import annotations

import pytest

from app.services.retrieval.fusion import fuse, reciprocal_rank_fusion, weighted_fusion
from app.services.retrieval.vector_store import ScoredVector


def _sv(vector_id: str, score: float) -> ScoredVector:
    return ScoredVector(vector_id=vector_id, score=score, metadata={"id": vector_id})


def test_rrf_boosts_items_ranked_highly_by_both_retrievers():
    dense = [_sv("a", 0.9), _sv("b", 0.8), _sv("c", 0.7)]
    sparse = [_sv("b", 12.0), _sv("a", 8.0), _sv("d", 5.0)]

    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    ids = [r.vector_id for r in fused]

    # "a" and "b" are top-2 in both lists; "c" and "d" only appear in one list each.
    assert ids[0] in ("a", "b")
    assert ids[1] in ("a", "b")
    assert set(ids) == {"a", "b", "c", "d"}


def test_rrf_ignores_raw_score_scale_only_uses_rank():
    # Wildly different score scales (cosine vs BM25) shouldn't matter to RRF.
    dense = [_sv("x", 0.99)]
    sparse = [_sv("y", 500.0)]
    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    # Both rank #1 in their own list -> equal RRF score -> order between them is
    # not asserted, but both must be present with identical fused scores.
    assert {r.vector_id for r in fused} == {"x", "y"}
    assert fused[0].score == pytest.approx(fused[1].score)


def test_rrf_empty_inputs():
    assert reciprocal_rank_fusion([], [], k=60) == []


def test_rrf_scores_are_rescaled_into_the_dense_confidence_scale():
    # Raw RRF (score = 1/(k+rank)) at k=60, rank=1 in both lists is ~0.033 total,
    # far below GROUNDING_CONFIDENCE_THRESHOLD (0.35) — hybrid mode would abstain on
    # every query if fusion didn't rescale into a comparable range.
    dense = [_sv("a", 0.95)]
    sparse = [_sv("a", 500.0)]
    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    assert fused[0].score == pytest.approx(1.0)  # rank #1 in both -> theoretical max


def test_rrf_single_retriever_match_still_above_default_confidence_threshold():
    dense = [_sv("a", 0.9)]
    fused = reciprocal_rank_fusion(dense, [], k=60)
    assert fused[0].score > 0.35


def test_weighted_fusion_favors_higher_weighted_retriever():
    dense = [_sv("a", 1.0), _sv("b", 0.0)]
    sparse = [_sv("b", 1.0), _sv("a", 0.0)]

    dense_heavy = weighted_fusion(dense, sparse, dense_weight=0.9, sparse_weight=0.1)
    assert dense_heavy[0].vector_id == "a"

    sparse_heavy = weighted_fusion(dense, sparse, dense_weight=0.1, sparse_weight=0.9)
    assert sparse_heavy[0].vector_id == "b"


def test_weighted_fusion_normalizes_disjoint_scales():
    dense = [_sv("a", 0.95), _sv("b", 0.10)]
    sparse = [_sv("c", 500.0), _sv("d", 1.0)]
    fused = weighted_fusion(dense, sparse, dense_weight=0.5, sparse_weight=0.5)
    assert {r.vector_id for r in fused} == {"a", "b", "c", "d"}
    # Top-scored item from each retriever should end up with the highest fused score.
    top_ids = {fused[0].vector_id, fused[1].vector_id}
    assert top_ids == {"a", "c"}


def test_weighted_fusion_single_result_gets_max_normalized_score():
    fused = weighted_fusion([_sv("a", 0.5)], [], dense_weight=1.0, sparse_weight=0.0)
    assert fused[0].score == pytest.approx(1.0)


def test_fuse_dispatches_to_correct_method():
    dense = [_sv("a", 1.0)]
    sparse = [_sv("b", 1.0)]
    rrf_result = fuse(dense, sparse, method="rrf", rrf_k=60, dense_weight=0.5, sparse_weight=0.5)
    weighted_result = fuse(dense, sparse, method="weighted", rrf_k=60, dense_weight=0.5, sparse_weight=0.5)
    assert {r.vector_id for r in rrf_result} == {"a", "b"}
    assert {r.vector_id for r in weighted_result} == {"a", "b"}


def test_fuse_unknown_method_raises():
    with pytest.raises(ValueError):
        fuse([], [], method="bogus", rrf_k=60, dense_weight=0.5, sparse_weight=0.5)
