from __future__ import annotations

from app.services.query_intelligence.rewriter import rewrite_follow_up


class FakeLLMClient:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def complete(self, system, user, max_tokens, temperature):
        self.calls.append((system, user, max_tokens, temperature))
        return self.response


class FailingLLMClient:
    def complete(self, *args, **kwargs):
        raise RuntimeError("upstream failure")


def test_rewrite_with_no_history_returns_original_unchanged():
    client = FakeLLMClient("should not be called")
    result = rewrite_follow_up("What about the second quarter?", [], client)
    assert result == "What about the second quarter?"
    assert client.calls == []


def test_rewrite_uses_history_to_resolve_reference():
    client = FakeLLMClient("What was Acme's Q2 2025 revenue?")
    history = [("What was Acme's Q1 2025 revenue?", "$38 million.")]
    result = rewrite_follow_up("What about Q2?", history, client)
    assert result == "What was Acme's Q2 2025 revenue?"
    assert "Q1 2025 revenue" in client.calls[0][1]  # history passed into the user prompt


def test_rewrite_strips_quotes_and_whitespace():
    client = FakeLLMClient('  "What was Q2 revenue?"  ')
    result = rewrite_follow_up("What about Q2?", [("Q1?", "answer")], client)
    assert result == "What was Q2 revenue?"


def test_rewrite_falls_back_to_original_on_llm_failure():
    result = rewrite_follow_up("What about Q2?", [("Q1?", "answer")], FailingLLMClient())
    assert result == "What about Q2?"


def test_rewrite_falls_back_when_llm_returns_empty_string():
    client = FakeLLMClient("")
    result = rewrite_follow_up("What about Q2?", [("Q1?", "answer")], client)
    assert result == "What about Q2?"
