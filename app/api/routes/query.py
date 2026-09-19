from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_dependency, settings_dependency
from app.core.config import Settings
from app.schemas.query import (
    CitationValidationStats,
    QueryIntelligenceStats,
    QueryRequest,
    QueryResponse,
    RetrievalStats,
    SourceRef,
    UnsupportedClaim,
)
from app.services.generation.llm_client import LLMNotConfiguredError
from app.services.query_service import run_query_pipeline

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    db: Session = Depends(db_dependency),
    settings: Settings = Depends(settings_dependency),
):
    try:
        pipeline_result = run_query_pipeline(request, db, settings)
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    generation = pipeline_result.generation
    qi_result = pipeline_result.qi_result

    return QueryResponse(
        answer=generation.answer,
        confidence=generation.confidence,
        sources=[
            SourceRef(
                document_id=s.document_id,
                document_name=s.document_name,
                page=s.page,
                chunk_id=s.chunk_id,
                relevance_score=round(s.score, 4),
                content_type=s.content_type,
            )
            for s in generation.sources
        ],
        retrieval=RetrievalStats(
            retrieved_chunks=generation.retrieved_count,
            selected_chunks=generation.selected_count,
            context_tokens=generation.context_tokens,
            retrieval_latency_ms=round(pipeline_result.retrieval_latency_ms, 2),
            reranking_latency_ms=(
                round(pipeline_result.reranking_latency_ms, 2)
                if pipeline_result.reranking_latency_ms is not None
                else None
            ),
            generation_latency_ms=round(generation.generation_latency_ms, 2),
            total_latency_ms=round(pipeline_result.total_latency_ms, 2),
            matched_content_types=sorted(pipeline_result.matched_content_types),
            reranked=settings.reranker_enabled,
            source_distribution=generation.source_distribution,
            dropped_low_relevance=generation.dropped_low_relevance,
            dropped_diversity_cap=generation.dropped_diversity_cap,
            truncated_chunks=generation.truncated_chunks,
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
                retrieval_trace=pipeline_result.retrieval_trace,
            )
            if qi_result is not None
            else None
        ),
        citation_validation=(
            CitationValidationStats(
                total_claims=generation.citation_validation.total_claims,
                supported_claims=generation.citation_validation.supported_claims,
                citation_correctness=generation.citation_validation.citation_correctness,
                unsupported_claims=[
                    UnsupportedClaim(
                        sentence=c.sentence,
                        citation_numbers=c.citation_numbers,
                        overlap_ratio=c.overlap_ratio,
                        missing_numbers=c.missing_numbers,
                        missing_proper_nouns=c.missing_proper_nouns,
                    )
                    for c in generation.citation_validation.unsupported_claims
                ],
            )
            if generation.citation_validation is not None
            else None
        ),
    )
