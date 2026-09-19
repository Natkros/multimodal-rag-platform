from __future__ import annotations

from app.services.evaluation.content_metrics import (
    aggregate_content_metrics,
    hit_rate_at_k,
    is_relevant,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
    relevance_vector,
)


def test_is_relevant_case_insensitive_substring_match():
    assert is_relevant("Revenue was $42.3 million in Q2.", ["42.3 million"])
    assert is_relevant("REVENUE WAS $42.3 MILLION", ["42.3 million"])
    assert not is_relevant("Revenue was flat.", ["42.3 million"])


def test_is_relevant_no_substrings_is_never_relevant():
    assert not is_relevant("Anything at all.", [])


def test_relevance_vector():
    texts = ["contains cat", "contains dog", "contains cat and dog"]
    assert relevance_vector(texts, ["cat"]) == [True, False, True]


def test_hit_rate_at_k():
    assert hit_rate_at_k([False, False, True], k=3) == 1.0
    assert hit_rate_at_k([False, False, True], k=2) == 0.0


def test_precision_at_k():
    assert precision_at_k([True, False, True, False], k=4) == 0.5


def test_reciprocal_rank():
    assert reciprocal_rank([False, True, False]) == 0.5
    assert reciprocal_rank([False, False]) == 0.0


def test_ndcg_perfect_and_empty():
    assert ndcg_at_k([True, True], k=2) == 1.0
    assert ndcg_at_k([False, False], k=2) == 0.0


def test_aggregate_content_metrics_excludes_unanswerable():
    retrieved = [["it has cat in it"], ["nothing relevant"]]
    substrings = [["cat"], []]  # second query has no ground truth
    result = aggregate_content_metrics(retrieved, substrings, k_values=(1,))
    assert result["n_answerable_queries"] == 1
    assert result["n_unanswerable_queries"] == 1
    assert result["hit_rate@1"] == 1.0


def test_aggregate_content_metrics_empty_input():
    assert aggregate_content_metrics([], []) == {}
