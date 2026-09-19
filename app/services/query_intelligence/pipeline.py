"""Orchestrates Phase 8's query intelligence steps into one call the API route makes:
classify -> rewrite (if follow-up) -> re-classify -> decompose (if multi-part) ->
expand (if enabled and not decomposed) -> match a mentioned document (if none given
explicitly). Kept separate from app/api/routes/query.py so the whole pipeline is
testable without going through FastAPI/HTTP.

`history` is caller-supplied (not fetched internally) as of Phase 12 — real
persistence now lives in app/repositories/conversation_repository.py, and this module
only needs "the last few (question, answer) pairs," not where they came from. See
docs/decisions/0012-phase12-conversational-rag.md for why this replaced Phase 8's
in-memory conversation_store.py entirely rather than layering DB storage behind it.

Every LLM-backed step degrades independently: if the LLM isn't configured or a call
fails, that step's effect is simply skipped (original question stays as-is, no
sub-questions, no expansion) — never a 500. The route's own required LLM call (for
generation) still returns 503 when unconfigured, since generation has no fallback;
query intelligence does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings
from app.services.generation.llm_client import LLMClient, LLMNotConfiguredError, get_llm_client
from app.services.query_intelligence.analysis import QueryAnalysis, classify_query
from app.services.query_intelligence.decomposition import decompose_query
from app.services.query_intelligence.document_matcher import find_mentioned_document
from app.services.query_intelligence.expansion import expand_query
from app.services.query_intelligence.rewriter import rewrite_follow_up


@dataclass
class QueryIntelligenceResult:
    original_question: str
    effective_question: str
    rewritten: bool
    analysis: QueryAnalysis
    sub_questions: list[str] = field(default_factory=list)
    expansion_variants: list[str] = field(default_factory=list)
    matched_document_id: str | None = None


def _try_get_llm_client(settings: Settings) -> LLMClient | None:
    try:
        return get_llm_client(settings)
    except LLMNotConfiguredError:
        return None


def process_query(
    question: str,
    history: list[tuple[str, str]],
    explicit_document_ids: list[str] | None,
    documents: list[tuple[str, str]],
    settings: Settings,
) -> QueryIntelligenceResult:
    analysis = classify_query(
        question, has_history=bool(history), short_word_threshold=settings.query_short_word_threshold
    )

    effective_question = question
    rewritten = False
    if settings.query_rewrite_enabled and analysis.is_follow_up and history:
        llm_client = _try_get_llm_client(settings)
        if llm_client is not None:
            effective_question = rewrite_follow_up(question, history, llm_client)
            rewritten = effective_question != question

    # Multi-part detection (and entity extraction) runs again on the resolved wording
    # — a follow-up like "what about 2023 and 2024?" only reveals it's multi-part once
    # rewritten. is_follow_up/is_ambiguous/is_short stay from the *original* question,
    # though: once rewritten, the resolved text no longer looks like a follow-up (it's
    # self-contained by construction), and overwriting those fields with that would
    # misreport what actually happened for this request.
    resolved_analysis = classify_query(
        effective_question,
        has_history=bool(history),
        short_word_threshold=settings.query_short_word_threshold,
    )
    combined_analysis = QueryAnalysis(
        word_count=analysis.word_count,
        is_short=analysis.is_short,
        is_ambiguous=analysis.is_ambiguous,
        is_follow_up=analysis.is_follow_up,
        is_multi_part=resolved_analysis.is_multi_part,
        mentioned_years=resolved_analysis.mentioned_years,
        mentioned_quarters=resolved_analysis.mentioned_quarters,
    )

    sub_questions: list[str] = []
    if settings.query_decomposition_enabled and combined_analysis.is_multi_part:
        llm_client = _try_get_llm_client(settings)
        if llm_client is not None:
            sub_questions = decompose_query(effective_question, llm_client)

    expansion_variants: list[str] = []
    if settings.query_expansion_enabled and not sub_questions:
        llm_client = _try_get_llm_client(settings)
        if llm_client is not None:
            expansion_variants = expand_query(effective_question, llm_client)

    matched_document_id = None
    if not explicit_document_ids:
        matched_document_id = find_mentioned_document(effective_question, documents)

    return QueryIntelligenceResult(
        original_question=question,
        effective_question=effective_question,
        rewritten=rewritten,
        analysis=combined_analysis,
        sub_questions=sub_questions,
        expansion_variants=expansion_variants,
        matched_document_id=matched_document_id,
    )
