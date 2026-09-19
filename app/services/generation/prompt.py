"""Grounded-generation prompt construction. See docs/architecture.md §9 (Phase 10 rules)."""
from __future__ import annotations

from app.services.retrieval.retriever import RetrievedChunk

SYSTEM_PROMPT = """You are a document question-answering assistant. You must answer \
using ONLY the evidence provided in the context below.

Rules:
1. Use only the retrieved evidence to answer. Do not use outside knowledge.
2. Every factual claim must be followed by a citation marker like [1], [2] referencing \
the numbered source it came from.
3. If the context does not contain enough information to answer, say exactly: \
"I could not find sufficient evidence in the indexed documents to answer this question." \
Do not guess.
4. Clearly distinguish evidence (what a source states) from inference (your own reasoning \
connecting sources) by prefacing inferential sentences with "Based on the above,".
5. Be concise and directly answer the question first, then support it."""


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        loc = f"{chunk.document_name}"
        if chunk.page is not None:
            loc += f", page {chunk.page}"
        if chunk.section:
            loc += f", section '{chunk.section}'"
        if chunk.content_type != "text":
            loc += f" ({chunk.content_type})"
        lines.append(f"[{i}] Source: {loc}\n{chunk.text}")
    return "\n\n".join(lines)


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    context = build_context_block(chunks)
    return f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"
