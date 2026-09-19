from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_dependency, settings_dependency
from app.core.config import Settings
from app.repositories.document_repository import DocumentRepository
from app.schemas.query import (
    QueryIntelligenceStats,
    QueryRequest,
    QueryResponse,
    RetrievalStats,
    RetrievalTraceEntry,
    SourceRef,
)
from app.services.embeddings.factory import get_embedder
from app.services.generation.generator import generate_answer
from app.services.generation.llm_client import LLMNotConfiguredError, get_llm_client
from app.services.query_intelligence import conversation_store
from app.services.query_intelligence.pipeline import process_query
from app.services.reranking.reranker import get_reranker
from app.services.retrieval.factory import get_retriever, get_vector_store
from app.services.retrieval.retriever import RetrievedChunk

router = APIRouter(tags=["query"])


def _merge_keep_best(chunk_lists: list[list[RetrievedChunk]]) -> list[RetrievedChunk]:
    """Multiple retrieval calls (decomposition/expansion) can return the same chunk —
    keep the highest score seen for it, then rank by that score."""
    best: dict[str, RetrievedChunk] = {}
    for chunks in chunk_lists:
        for chunk in chunks:
            existing = best.get(chunk.chunk_id)
            if existing is None or chunk.score > existing.score:
                best[chunk.chunk_id] = chunk
    return sorted(best.values(), key=lambda c: c.score, reverse=True)


@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    db: Session = Depends(db_dependency),
    settings: Settings = Depends(settings_dependency),
):
    total_start = time.perf_counter()
    repo = DocumentRepository(db)

    qi_result = None
    effective_question = request.question
    effective_document_ids = request.document_ids
    if settings.query_intelligence_enabled:
        documents = [(d.document_id, d.filename) for d in repo.list_all()]
        qi_result = process_query(
            request.question, request.conversation_id, request.document_ids, documents, settings
        )
        effective_question = qi_result.effective_question
        if not effective_document_ids and qi_result.matched_document_id:
            effective_document_ids = [qi_result.matched_document_id]

    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings, embedder.dimension)
    retriever = get_retriever(settings, embedder, vector_store)

    # With reranking on, retrieve a wider candidate pool than the caller asked for —
    # the reranker needs something to actually choose among — and trim to top_k only
    # after rescoring. Without it, retrieve exactly top_k as before (unchanged
    # Phase 1-6 behavior).
    pool_k = max(request.top_k, settings.rerank_candidate_pool) if settings.reranker_enabled else request.top_k

    # Decomposition replaces the single query with several independent ones;
    # expansion adds variants alongside the original. Each is a distinct, tracked
    # retrieval operation (Phase 8 requirement), then merged by best score per chunk.
    queries_to_retrieve = [effective_question]
    if qi_result and qi_result.sub_questions:
        queries_to_retrieve = qi_result.sub_questions
    elif qi_result and qi_result.expansion_variants:
        queries_to_retrieve = [effective_question, *qi_result.expansion_variants]

    retrieval_start = time.perf_counter()
    retrieval_trace: list[RetrievalTraceEntry] = []
    all_matched_content_types: set[str] = set()
    chunk_lists: list[list[RetrievedChunk]] = []
    for sub_query in queries_to_retrieve:
        result = retriever.retrieve_with_classification(
            sub_query, top_k=pool_k, document_ids=effective_document_ids
        )
        chunk_lists.append(result.chunks)
        all_matched_content_types.update(result.matched_content_types)
        retrieval_trace.append(
            RetrievalTraceEntry(
                query=sub_query,
                matched_content_types=result.matched_content_types,
                chunk_count=len(result.chunks),
            )
        )
    merged_candidates = _merge_keep_best(chunk_lists)[:pool_k]
    retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000

    reranking_latency_ms = None
    if settings.reranker_enabled:
        rerank_start = time.perf_counter()
        reranker = get_reranker(settings)
        retrieved = reranker.rerank(effective_question, merged_candidates, top_k=request.top_k)
        reranking_latency_ms = (time.perf_counter() - rerank_start) * 1000
    else:
        retrieved = merged_candidates[: request.top_k]

    try:
        llm_client = get_llm_client(settings)
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = generate_answer(effective_question, retrieved, llm_client, settings)

    if settings.query_intelligence_enabled:
        conversation_store.append_turn(
            request.conversation_id, request.question, result.answer, settings.conversation_history_max_turns
        )

    total_latency_ms = (time.perf_counter() - total_start) * 1000

    return QueryResponse(
        answer=result.answer,
        confidence=result.confidence,
        sources=[
            SourceRef(
                document_id=s.document_id,
                document_name=s.document_name,
                page=s.page,
                chunk_id=s.chunk_id,
                relevance_score=round(s.score, 4),
                content_type=s.content_type,
            )
            for s in result.sources
        ],
        retrieval=RetrievalStats(
            retrieved_chunks=result.retrieved_count,
            selected_chunks=result.selected_count,
            context_tokens=result.context_tokens,
            retrieval_latency_ms=round(retrieval_latency_ms, 2),
            reranking_latency_ms=round(reranking_latency_ms, 2) if reranking_latency_ms is not None else None,
            generation_latency_ms=round(result.generation_latency_ms, 2),
            total_latency_ms=round(total_latency_ms, 2),
            matched_content_types=sorted(all_matched_content_types),
            reranked=settings.reranker_enabled,
        ),
        query_intelligence=(
            QueryIntelligenceStats(
                original_question=qi_result.original_question,
                effective_question=qi_result.effective_question,
                rewritten=qi_result.rewritten,
                is_short=qi_result.analysis.is_short,
                is_ambiguous=qi_result.analysis.is_ambiguous,
                is_multi_part=qi_result.analysis.is_multi_part,
                is_follow_up=qi_result.analysis.is_follow_up,
                mentioned_years=qi_result.analysis.mentioned_years,
                mentioned_quarters=qi_result.analysis.mentioned_quarters,
                sub_questions=qi_result.sub_questions,
                expansion_variants=qi_result.expansion_variants,
                matched_document_id=qi_result.matched_document_id,
                retrieval_trace=retrieval_trace,
            )
            if qi_result is not None
            else None
        ),
    )
