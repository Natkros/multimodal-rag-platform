from __future__ import annotations

from app.services.query_intelligence.expansion import expand_query


class FakeLLMClient:
    def __init__(self, response: str):
        self.response = response

    def complete(self, system, user, max_tokens, temperature):
        return self.response


class FailingLLMClient:
    def complete(self, *args, **kwargs):
        raise RuntimeError("upstream failure")


def test_expand_returns_alternative_phrasings():
    client = FakeLLMClient("How much did Acme earn in Q2 2025?\nWhat was Acme's Q2 2025 income?")
    result = expand_query("What was Acme's Q2 2025 revenue?", client)
    assert result == ["How much did Acme earn in Q2 2025?", "What was Acme's Q2 2025 income?"]


def test_expand_filters_out_identical_variant():
    client = FakeLLMClient("What was Acme's Q2 2025 revenue?\nA genuinely different phrasing?")
    result = expand_query("What was Acme's Q2 2025 revenue?", client)
    assert result == ["A genuinely different phrasing?"]


def test_expand_returns_empty_list_on_llm_failure():
    result = expand_query("What was Acme's revenue?", FailingLLMClient())
    assert result == []


def test_expand_strips_numbering():
    client = FakeLLMClient("- Variant one\n- Variant two")
    result = expand_query("Original question", client)
    assert result == ["Variant one", "Variant two"]
