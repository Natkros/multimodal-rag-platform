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
    reranking_latency_ms: float | None = None  # None means reranking was not applied
    generation_latency_ms: float
    total_latency_ms: float
    # Content type(s) the query's wording pointed retrieval at — [] means an
    # unrestricted ("hybrid") search across text/table/image. See
    # app/services/retrieval/query_classifier.py.
    matched_content_types: list[str] = []
    reranked: bool = False  # RERANKER_ENABLED at request time — see Phase 7 / ADR 0007
    # Phase 9 context engineering — see app/services/generation/context_builder.py
    source_distribution: dict[str, int] = {}  # document_name -> chunks selected from it
    dropped_low_relevance: int = 0
    dropped_diversity_cap: int = 0
    truncated_chunks: int = 0


class RetrievalTraceEntry(BaseModel):
    """One retrieval operation — Phase 8 decomposition/expansion can trigger several
    per request, each tracked separately per the project brief."""

    query: str
    matched_content_types: list[str] = []
    chunk_count: int


class QueryIntelligenceStats(BaseModel):
    """Present only when QUERY_INTELLIGENCE_ENABLED=true — see
    app/services/query_intelligence/pipeline.py and ADR 0008."""

    original_question: str
    effective_question: str
    rewritten: bool
    is_short: bool
    is_ambiguous: bool
    is_multi_part: bool
    is_follow_up: bool
    mentioned_years: list[str] = []
    mentioned_quarters: list[str] = []
    sub_questions: list[str] = []
    expansion_variants: list[str] = []
    matched_document_id: str | None = None
    retrieval_trace: list[RetrievalTraceEntry] = []


class UnsupportedClaim(BaseModel):
    sentence: str
    citation_numbers: list[int]
    overlap_ratio: float
    missing_numbers: list[str] = []
    missing_proper_nouns: list[str] = []


class CitationValidationStats(BaseModel):
    """Deterministic check (word-overlap + exact-number/proper-noun matching) of
    whether each cited sentence is actually supported by the chunk(s) it cites — see
    app/services/generation/citation_validator.py and ADR 0011."""

    total_claims: int
    supported_claims: int
    citation_correctness: float | None  # None when the answer had no citations to check
    unsupported_claims: list[UnsupportedClaim] = []


class QueryResponse(BaseModel):
    answer: str
    confidence: str  # "high" | "low" | "abstained"
    sources: list[SourceRef]
    retrieval: RetrievalStats
    query_intelligence: QueryIntelligenceStats | None = None
    citation_validation: CitationValidationStats | None = None
