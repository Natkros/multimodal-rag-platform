from __future__ import annotations

from app.services.retrieval.mmr import average_pairwise_similarity, select_with_mmr
from app.services.retrieval.retriever import RetrievedChunk


def _chunk(chunk_id: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        document_name=f"{chunk_id}.txt",
        text=chunk_id,
        page=None,
        section=None,
        score=score,
    )


def test_lambda_one_matches_plain_relevance_ranking():
    """lambda_param=1.0 should ignore diversity entirely and just take the
    highest-scored candidates in order, same as Phase 1-9's plain top-k slice."""
    candidates = [_chunk("a", 0.9), _chunk("b", 0.7), _chunk("c", 0.5), _chunk("d", 0.3)]
    vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]  # a/b identical, c/d identical

    result = select_with_mmr(candidates, vectors, top_k=2, lambda_param=1.0)

    assert [c.chunk_id for c in result] == ["a", "b"]


def test_lambda_favors_diversity_over_a_near_duplicate():
    """With diversity weighted in, a near-duplicate of the top result should lose
    out to a lower-scored but distinct candidate."""
    candidates = [_chunk("a", 0.9), _chunk("a_dup", 0.85), _chunk("c", 0.5)]
    vectors = [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]  # a and a_dup are near-identical

    result = select_with_mmr(candidates, vectors, top_k=2, lambda_param=0.5)

    assert result[0].chunk_id == "a"
    assert result[1].chunk_id == "c"  # not a_dup, despite its higher raw score


def test_select_with_mmr_returns_empty_for_no_candidates():
    assert select_with_mmr([], [], top_k=5, lambda_param=0.5) == []


def test_select_with_mmr_respects_top_k_smaller_than_pool():
    candidates = [_chunk(str(i), 1.0 - i * 0.1) for i in range(5)]
    vectors = [[float(i), 0.0] for i in range(5)]
    result = select_with_mmr(candidates, vectors, top_k=3, lambda_param=1.0)
    assert len(result) == 3


def test_average_pairwise_similarity_identical_vectors_is_one():
    assert average_pairwise_similarity([[1.0, 0.0], [1.0, 0.0]]) == 1.0


def test_average_pairwise_similarity_orthogonal_vectors_is_zero():
    assert average_pairwise_similarity([[1.0, 0.0], [0.0, 1.0]]) == 0.0


def test_average_pairwise_similarity_single_vector_is_zero():
    assert average_pairwise_similarity([[1.0, 0.0]]) == 0.0


def test_average_pairwise_similarity_empty_is_zero():
    assert average_pairwise_similarity([]) == 0.0
