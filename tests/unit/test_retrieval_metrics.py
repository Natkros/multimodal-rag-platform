from __future__ import annotations

from app.services.evaluation.retrieval_metrics import (
    hit_rate_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_perfect():
    assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 1.0


def test_recall_at_k_partial():
    assert recall_at_k(["a", "x", "y"], {"a", "b"}, k=3) == 0.5


def test_recall_at_k_no_relevant_docs_returns_zero():
    assert recall_at_k(["a", "b"], set(), k=3) == 0.0


def test_precision_at_k():
    assert precision_at_k(["a", "x", "y"], {"a"}, k=3) == 1 / 3


def test_reciprocal_rank_first_hit():
    assert reciprocal_rank(["x", "a", "b"], {"a"}) == 0.5


def test_reciprocal_rank_no_hit():
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_ndcg_perfect_ranking_is_one():
    assert ndcg_at_k(["a", "b"], {"a", "b"}, k=2) == 1.0


def test_hit_rate_at_k():
    assert hit_rate_at_k(["x", "a"], {"a"}, k=2) == 1.0
    assert hit_rate_at_k(["x", "y"], {"a"}, k=2) == 0.0
