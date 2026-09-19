from __future__ import annotations

from app.services.query_intelligence.decomposition import decompose_query


class FakeLLMClient:
    def __init__(self, response: str):
        self.response = response

    def complete(self, system, user, max_tokens, temperature):
        return self.response


class FailingLLMClient:
    def complete(self, *args, **kwargs):
        raise RuntimeError("upstream failure")


def test_decompose_splits_into_multiple_sub_questions():
    client = FakeLLMClient(
        "What was Acme's 2023 revenue?\n"
        "What was Acme's 2024 revenue?\n"
        "What drove Acme's revenue growth?"
    )
    result = decompose_query("Compare revenue growth between 2023 and 2024 and explain the drivers.", client)
    assert result == [
        "What was Acme's 2023 revenue?",
        "What was Acme's 2024 revenue?",
        "What drove Acme's revenue growth?",
    ]


def test_decompose_strips_numbering_and_bullets():
    client = FakeLLMClient("- What was the 2023 revenue?\n- What was the 2024 revenue?")
    result = decompose_query("Compare 2023 and 2024 revenue.", client)
    assert result == ["What was the 2023 revenue?", "What was the 2024 revenue?"]


def test_decompose_single_line_response_returns_empty_list():
    # Model judged the question non-decomposable -> caller should treat this the same
    # as "no decomposition happened."
    client = FakeLLMClient("What is Acme's cancellation policy?")
    result = decompose_query("What is Acme's cancellation policy?", client)
    assert result == []


def test_decompose_returns_empty_list_on_llm_failure():
    result = decompose_query("Compare 2023 and 2024 revenue.", FailingLLMClient())
    assert result == []


def test_decompose_filters_blank_lines():
    client = FakeLLMClient("Question one?\n\nQuestion two?\n\n")
    result = decompose_query("Some multi-part question?", client)
    assert result == ["Question one?", "Question two?"]
