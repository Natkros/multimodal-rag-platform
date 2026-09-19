from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_dependency, settings_dependency
from app.core.config import Settings
from app.schemas.query import QueryRequest, QueryResponse, RetrievalStats, SourceRef
from app.services.embeddings.factory import get_embedder
from app.services.generation.generator import generate_answer
from app.services.generation.llm_client import LLMNotConfiguredError, get_llm_client
from app.services.retrieval.factory import get_vector_store
from app.services.retrieval.retriever import DenseRetriever

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(
    request: QueryRequest,
    db: Session = Depends(db_dependency),
    settings: Settings = Depends(settings_dependency),
):
    total_start = time.perf_counter()

    embedder = get_embedder(settings)
    vector_store = get_vector_store(settings, embedder.dimension)
    retriever = DenseRetriever(embedder=embedder, vector_store=vector_store)

    retrieval_start = time.perf_counter()
    retrieval_result = retriever.retrieve_with_classification(
        request.question, top_k=request.top_k, document_ids=request.document_ids
    )
    retrieved = retrieval_result.chunks
    retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000

    try:
        llm_client = get_llm_client(settings)
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = generate_answer(request.question, retrieved, llm_client, settings)

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
            generation_latency_ms=round(result.generation_latency_ms, 2),
            total_latency_ms=round(total_latency_ms, 2),
            matched_content_types=retrieval_result.matched_content_types,
        ),
    )
