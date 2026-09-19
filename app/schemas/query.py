from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = None


class SourceRef(BaseModel):
    document_id: str
    document_name: str
    page: int | None = None
    chunk_id: str
    relevance_score: float
    content_type: str = "text"  # text | table | image — see Phase 5


class RetrievalStats(BaseModel):
    retrieved_chunks: int
    selected_chunks: int
    context_tokens: int
    retrieval_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float
    # Content type(s) the query's wording pointed retrieval at — [] means an
    # unrestricted ("hybrid") search across text/table/image. See
    # app/services/retrieval/query_classifier.py.
    matched_content_types: list[str] = []


class QueryResponse(BaseModel):
    answer: str
    confidence: str  # "high" | "low" | "abstained"
    sources: list[SourceRef]
    retrieval: RetrievalStats
