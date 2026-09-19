from __future__ import annotations

import pytest

from app.services.query_intelligence import conversation_store as cs


@pytest.fixture(autouse=True)
def _clean_store():
    cs.reset_all()
    yield
    cs.reset_all()


def test_get_history_empty_for_new_conversation():
    assert cs.get_history("conv-1", max_turns=5) == []


def test_get_history_none_conversation_id_returns_empty():
    assert cs.get_history(None, max_turns=5) == []


def test_append_and_retrieve_turn():
    cs.append_turn("conv-1", "What was Q1 revenue?", "$38 million.", max_turns=5)
    assert cs.get_history("conv-1", max_turns=5) == [("What was Q1 revenue?", "$38 million.")]


def test_history_isolated_per_conversation():
    cs.append_turn("conv-1", "Q1?", "A1", max_turns=5)
    cs.append_turn("conv-2", "Q2?", "A2", max_turns=5)
    assert cs.get_history("conv-1", max_turns=5) == [("Q1?", "A1")]
    assert cs.get_history("conv-2", max_turns=5) == [("Q2?", "A2")]


def test_history_capped_at_max_turns():
    for i in range(10):
        cs.append_turn("conv-1", f"Q{i}?", f"A{i}", max_turns=3)
    history = cs.get_history("conv-1", max_turns=10)
    assert len(history) == 3
    assert history == [("Q7?", "A7"), ("Q8?", "A8"), ("Q9?", "A9")]


def test_reset_all_clears_every_conversation():
    cs.append_turn("conv-1", "Q?", "A", max_turns=5)
    cs.reset_all()
    assert cs.get_history("conv-1", max_turns=5) == []


def test_append_turn_none_conversation_id_is_noop():
    cs.append_turn(None, "Q?", "A", max_turns=5)
    assert cs.get_history(None, max_turns=5) == []
