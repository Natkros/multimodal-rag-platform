from __future__ import annotations

from app.core.config import get_settings
from app.services.query_intelligence.pipeline import process_query


class ScriptedLLMClient:
    """Returns a different canned response depending on which system prompt is used,
    so one fake client can stand in for rewrite/decompose/expand calls."""

    def __init__(self, rewrite=None, decompose=None, expand=None):
        self.rewrite = rewrite
        self.decompose = decompose
        self.expand = expand

    def complete(self, system, user, max_tokens, temperature):
        if "rewrite" in system.lower():
            return self.rewrite or ""
        if "break a multi-part" in system.lower():
            return self.decompose or ""
        if "alternative phrasings" in system.lower():
            return self.expand or ""
        raise AssertionError(f"Unexpected system prompt: {system[:50]}")


def _base_settings(**overrides):
    settings = get_settings().model_copy(
        update={
            "query_intelligence_enabled": True,
            "query_rewrite_enabled": True,
            "query_decomposition_enabled": True,
            "query_expansion_enabled": False,
            **overrides,
        }
    )
    return settings


def test_process_query_no_history_no_rewrite(monkeypatch):
    settings = _base_settings()
    result = process_query("What is Acme's cancellation policy?", [], None, [], settings)
    assert result.effective_question == "What is Acme's cancellation policy?"
    assert result.rewritten is False


def test_process_query_rewrites_follow_up_using_history(monkeypatch):
    import app.services.query_intelligence.pipeline as pipeline_module

    history = [("What was Q1 2025 revenue?", "$38 million.")]
    fake_client = ScriptedLLMClient(rewrite="What was Acme's Q2 2025 revenue?")
    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda settings: fake_client)

    settings = _base_settings()
    result = process_query("What about Q2?", history, None, [], settings)

    assert result.rewritten is True
    assert result.effective_question == "What was Acme's Q2 2025 revenue?"


def test_process_query_decomposes_multi_part_question(monkeypatch):
    import app.services.query_intelligence.pipeline as pipeline_module

    fake_client = ScriptedLLMClient(
        decompose="What was 2023 revenue?\nWhat was 2024 revenue?\nWhat drove growth?"
    )
    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda settings: fake_client)

    settings = _base_settings()
    result = process_query(
        "Compare revenue growth between 2023 and 2024 and explain the primary drivers.",
        [],
        None,
        [],
        settings,
    )

    assert result.sub_questions == ["What was 2023 revenue?", "What was 2024 revenue?", "What drove growth?"]


def test_process_query_expansion_only_when_enabled_and_not_decomposed(monkeypatch):
    import app.services.query_intelligence.pipeline as pipeline_module

    fake_client = ScriptedLLMClient(expand="An alternative phrasing of the question.")
    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda settings: fake_client)

    settings = _base_settings(query_expansion_enabled=True, query_decomposition_enabled=False)
    result = process_query("What is Acme's cancellation policy?", [], None, [], settings)

    assert result.expansion_variants == ["An alternative phrasing of the question."]


def test_process_query_llm_not_configured_degrades_gracefully(monkeypatch):
    import app.services.query_intelligence.pipeline as pipeline_module
    from app.services.generation.llm_client import LLMNotConfiguredError

    def raise_not_configured(_settings):
        raise LLMNotConfiguredError("no key")

    monkeypatch.setattr(pipeline_module, "get_llm_client", raise_not_configured)

    history = [("What was Q1 revenue?", "$38 million.")]
    settings = _base_settings()
    result = process_query("What about Q2?", history, None, [], settings)

    assert result.rewritten is False
    assert result.effective_question == "What about Q2?"
    assert result.sub_questions == []


def test_process_query_reports_is_follow_up_true_even_after_successful_rewrite(monkeypatch):
    """Regression: the resolved/rewritten question no longer *looks* like a follow-up
    (it's self-contained by construction), so is_follow_up must come from the
    original question's classification, not be overwritten by re-classifying the
    already-rewritten text."""
    import app.services.query_intelligence.pipeline as pipeline_module

    history = [("What was Q1 2025 revenue?", "$38 million.")]
    fake_client = ScriptedLLMClient(rewrite="What was Acme's Q2 2025 revenue?")
    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda settings: fake_client)

    settings = _base_settings()
    result = process_query("What about Q2?", history, None, [], settings)

    assert result.analysis.is_follow_up is True
    assert result.analysis.is_multi_part is False


def test_process_query_matches_mentioned_document_when_not_explicit():
    settings = _base_settings()
    documents = [("doc-1", "acme_vendor_security_policy.docx")]
    result = process_query("In the vendor security policy, what is required?", [], None, documents, settings)
    assert result.matched_document_id == "doc-1"


def test_process_query_does_not_match_document_when_explicit_ids_given():
    settings = _base_settings()
    documents = [("doc-1", "acme_vendor_security_policy.docx")]
    result = process_query(
        "In the vendor security policy, what is required?", [], ["doc-2"], documents, settings
    )
    assert result.matched_document_id is None
