from __future__ import annotations

from app.services.evaluation.retrieval_metrics import aggregate_metrics


def test_aggregate_excludes_unanswerable_queries_from_recall():
    retrieved = [["a", "b"], ["x", "y"]]
    relevant = [{"a"}, set()]  # second query is unanswerable (no ground truth)
    result = aggregate_metrics(retrieved, relevant, k_values=(1,))
    assert result["n_queries"] == 2
    assert result["n_answerable_queries"] == 1
    assert result["n_unanswerable_queries"] == 1
    assert result["recall@1"] == 1.0  # perfect on the one answerable query, not dragged to 0.5


def test_aggregate_all_unanswerable_returns_counts_only():
    result = aggregate_metrics([["a"]], [set()], k_values=(1,))
    assert result["n_answerable_queries"] == 0
    assert "recall@1" not in result


def test_aggregate_empty_input_returns_empty_dict():
    assert aggregate_metrics([], []) == {}
