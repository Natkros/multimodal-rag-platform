"""Minimal context construction for Phase 1 (full Phase 9 context engineering — source
prioritization, compression — extends this without changing the return shape)."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.chunking.chunker import estimate_tokens
from app.services.retrieval.retriever import RetrievedChunk


@dataclass
class BuiltContext:
    chunks: list[RetrievedChunk]
    total_tokens: int


def build_context(chunks: list[RetrievedChunk], max_tokens: int = 3000) -> BuiltContext:
    seen_text: set[str] = set()
    selected: list[RetrievedChunk] = []
    total = 0
    for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
        if chunk.text in seen_text:
            continue
        tokens = estimate_tokens(chunk.text)
        if total + tokens > max_tokens and selected:
            break
        selected.append(chunk)
        seen_text.add(chunk.text)
        total += tokens
    return BuiltContext(chunks=selected, total_tokens=total)
