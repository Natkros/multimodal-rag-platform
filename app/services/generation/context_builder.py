"""Phase 9 context engineering: dedupe, filter weak candidates, cap per-document
diversity, truncate oversized chunks (compression), pack into a token budget, and
report source distribution — all deterministic, no LLM call.

Every new behavior beyond Phase 1's dedupe+budget-trim is opt-in via config
(`context_relevance_floor_ratio`, `context_max_chunks_per_document`,
`context_compression_enabled`), defaulting to off/no-op so Phases 1-8's baseline
generation behavior is unchanged unless explicitly configured — same pattern as
hybrid retrieval and reranking. `source_distribution` is always computed since it's
pure reporting with no effect on which chunks get selected.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.services.chunking.chunker import estimate_tokens
from app.services.retrieval.retriever import RetrievedChunk


@dataclass
class BuiltContext:
    chunks: list[RetrievedChunk]
    total_tokens: int
    # document_name -> number of selected chunks from it, for transparency into
    # whether the final context leans on one source or several.
    source_distribution: dict[str, int] = field(default_factory=dict)
    dropped_low_relevance: int = 0  # chunks excluded by context_relevance_floor_ratio
    dropped_diversity_cap: int = 0  # chunks excluded by context_max_chunks_per_document
    truncated_chunks: int = 0  # chunks shortened by context_compression_enabled


def _truncate(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " […truncated]"


def build_context(
    chunks: list[RetrievedChunk],
    max_tokens: int = 3000,
    relevance_floor_ratio: float = 0.0,
    max_chunks_per_document: int | None = None,
    compression_enabled: bool = False,
    max_chunk_tokens: int = 300,
) -> BuiltContext:
    ranked = sorted(chunks, key=lambda c: c.score, reverse=True)

    # "Remove irrelevant context": drop anything scoring below a fraction of the top
    # result's score — a candidate that barely cleared the retriever's own cutoff but
    # trails the best match by a wide margin adds context-window cost without much
    # evidentiary value. Disabled (ratio=0) by default: everything retrieved is kept,
    # matching Phase 1-8 behavior exactly.
    if ranked and relevance_floor_ratio > 0:
        floor = ranked[0].score * relevance_floor_ratio
        filtered = [c for c in ranked if c.score >= floor]
        dropped_low_relevance = len(ranked) - len(filtered)
        ranked = filtered
    else:
        dropped_low_relevance = 0

    seen_text: set[str] = set()
    per_doc_count: Counter[str] = Counter()
    selected: list[RetrievedChunk] = []
    total = 0
    dropped_diversity_cap = 0
    truncated_chunks = 0

    for chunk in ranked:
        original_text = chunk.text
        if original_text in seen_text:
            continue

        if max_chunks_per_document is not None and per_doc_count[chunk.document_id] >= max_chunks_per_document:
            dropped_diversity_cap += 1
            continue

        text = original_text
        if compression_enabled:
            text = _truncate(original_text, max_chunk_tokens)
            if text != original_text:
                truncated_chunks += 1

        tokens = estimate_tokens(text)
        if total + tokens > max_tokens and selected:
            break

        if text != original_text:
            chunk = RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_name=chunk.document_name,
                text=text,
                page=chunk.page,
                section=chunk.section,
                score=chunk.score,
                content_type=chunk.content_type,
            )

        selected.append(chunk)
        seen_text.add(original_text)
        per_doc_count[chunk.document_id] += 1
        total += tokens

    source_distribution = dict(Counter(c.document_name for c in selected))

    return BuiltContext(
        chunks=selected,
        total_tokens=total,
        source_distribution=source_distribution,
        dropped_low_relevance=dropped_low_relevance,
        dropped_diversity_cap=dropped_diversity_cap,
        truncated_chunks=truncated_chunks,
    )
