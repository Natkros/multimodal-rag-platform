"""Phase 15: the /query endpoint's orchestration logic, extracted out of
app/api/routes/query.py into its own service so the route is a thin HTTP adapter
(parse request -> call this -> map result to QueryResponse) and the orchestration
itself (conversation history, query intelligence, multi-query retrieval + merge,
reranking, generation, conversation persistence) is testable without going through
FastAPI. Pure code motion — no behavior change; see
docs/decisions/0015-phase15-service-layer.md for why this was the one real
violation of the routes/services/repositories layering this project otherwise
already had since Phase 1.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.query import QueryRequest, RetrievalTraceEntry
from app.services.embeddings.factory import get_embedder
from app.services.generation.generator import GenerationResult, generate_answer
from app.services.generation.llm_client import get_llm_client
from app.services.query_intelligence.pipeline import QueryIntelligenceResult, process_query
from app.services.reranking.reranker import get_reranker
from app.services.retrieval.factory import get_retriever, get_vector_store
from app.services.retrieval.mmr import select_with_mmr
from app.services.retrieval.retriever import RetrievedChunk


@dataclass
class QueryPipelineResult:
    generation: GenerationResult
    qi_result: QueryIntelligenceResult | None
    retrieval_trace: list[RetrievalTraceEntry] = field(default_factory=list)
    matched_content_types: set[str] = field(default_factory=set)
    retrieval_latency_ms: float = 0.0
    reranking_latency_ms: float | None = None
    total_latency_ms: float = 0.0


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


def run_query_pipeline(request: QueryRequest, db: Session, settings: Settings) -> QueryPipelineResult:
    """Raises LLMNotConfiguredError (translated to a 503 by the route) when
    generation has no configured LLM — query intelligence's own LLM calls degrade
    to a no-op instead (see ADR 0008), since only generation has no fallback."""
    total_start = time.perf_counter()
    repo = DocumentRepository(db)
    conv_repo = ConversationRepository(db)

    # Conversation persistence (Phase 12) is independent of query intelligence
    # (Phase 8): a conversation_id always gets its turns recorded, even with
    # QUERY_INTELLIGENCE_ENABLED=false — rewriting/decomposition are an optional
    # enhancement layered on top of history that exists either way.
    history: list[tuple[str, str]] = []
    if request.conversation_id:
        conv_repo.get_or_create(request.conversation_id)
        if settings.query_intelligence_enabled:
            history = conv_repo.get_recent_turns(
                request.conversation_id, settings.conversation_history_max_turns
            )

    qi_result = None
    effective_question = request.question
    effective_document_ids = request.document_ids
    if settings.query_intelligence_enabled:
        documents = [(d.document_id, d.filename) for d in repo.list_all()]
        qi_result = process_query(request.question, history, request.document_ids, documents, settings)
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
    pool_k = (
        max(request.top_k, settings.rerank_candidate_pool) if settings.reranker_enabled else request.top_k
    )

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

    # When MMR (Phase 26) will also run, rerank the *whole* candidate pool rather
    # than trimming straight to top_k — MMR needs a real pool bigger than top_k to
    # choose diversity from, otherwise there's nothing left for it to select among.
    reranking_latency_ms = None
    if settings.reranker_enabled:
        rerank_start = time.perf_counter()
        reranker = get_reranker(settings)
        rerank_top_k = pool_k if settings.mmr_enabled else request.top_k
        candidate_pool = reranker.rerank(effective_question, merged_candidates, top_k=rerank_top_k)
        reranking_latency_ms = (time.perf_counter() - rerank_start) * 1000
    else:
        candidate_pool = merged_candidates

    if settings.mmr_enabled:
        candidate_vectors = embedder.embed_documents([c.text for c in candidate_pool])
        retrieved = select_with_mmr(candidate_pool, candidate_vectors, request.top_k, settings.mmr_lambda)
    else:
        retrieved = candidate_pool[: request.top_k]

    llm_client = get_llm_client(settings)  # raises LLMNotConfiguredError; route maps it to 503

    generation = generate_answer(effective_question, retrieved, llm_client, settings)

    if request.conversation_id:
        conv_repo.add_message(request.conversation_id, "user", request.question)
        conv_repo.add_message(
            request.conversation_id,
            "assistant",
            generation.answer,
            retrieved_source_chunk_ids=[s.chunk_id for s in generation.sources],
        )

    total_latency_ms = (time.perf_counter() - total_start) * 1000

    return QueryPipelineResult(
        generation=generation,
        qi_result=qi_result,
        retrieval_trace=retrieval_trace,
        matched_content_types=all_matched_content_types,
        retrieval_latency_ms=retrieval_latency_ms,
        reranking_latency_ms=reranking_latency_ms,
        total_latency_ms=total_latency_ms,
    )
