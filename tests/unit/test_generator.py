from __future__ import annotations

from app.core.config import get_settings
from app.services.generation.generator import ABSTENTION_TEXT, generate_answer
from app.services.retrieval.retriever import RetrievedChunk


class FakeLLMClient:
    def __init__(self, response="Answer with a citation [1]."):
        self.response = response

    def complete(self, system, user, max_tokens, temperature):
        return self.response


def _chunk(score, text="Acme's Q2 revenue was $42.3 million."):
    return RetrievedChunk(
        chunk_id="c1", document_id="d1", document_name="doc.txt", text=text, page=1, section=None, score=score
    )


def test_abstains_below_confidence_threshold():
    settings = get_settings().model_copy(update={"grounding_confidence_threshold": 0.5})
    result = generate_answer("Q?", [_chunk(0.3)], FakeLLMClient(), settings)
    assert result.confidence == "abstained"
    assert result.answer == ABSTENTION_TEXT
    assert result.sources == []


def test_answers_at_or_above_confidence_threshold():
    settings = get_settings().model_copy(update={"grounding_confidence_threshold": 0.5})
    result = generate_answer("Q?", [_chunk(0.5)], FakeLLMClient(), settings)
    assert result.confidence != "abstained"


def test_abstains_with_no_retrieved_chunks():
    settings = get_settings()
    result = generate_answer("Q?", [], FakeLLMClient(), settings)
    assert result.confidence == "abstained"


def test_high_confidence_threshold_is_configurable():
    settings = get_settings().model_copy(update={"grounding_high_confidence_threshold": 0.9})
    # 0.7 clears the default abstain floor but not this custom high-confidence bar.
    result = generate_answer("Q?", [_chunk(0.7)], FakeLLMClient(), settings)
    assert result.confidence == "low"


def test_high_confidence_label_when_above_threshold():
    settings = get_settings().model_copy(update={"grounding_high_confidence_threshold": 0.5})
    result = generate_answer("Q?", [_chunk(0.7)], FakeLLMClient(), settings)
    assert result.confidence == "high"


def test_confidence_threshold_boundary_is_inclusive():
    settings = get_settings().model_copy(update={"grounding_high_confidence_threshold": 0.6})
    result = generate_answer("Q?", [_chunk(0.6)], FakeLLMClient(), settings)
    assert result.confidence == "high"
