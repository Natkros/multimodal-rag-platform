from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import Settings
from app.services.generation.context_builder import build_context
from app.services.generation.llm_client import LLMClient
from app.services.generation.prompt import SYSTEM_PROMPT, build_user_prompt
from app.services.retrieval.retriever import RetrievedChunk

ABSTENTION_TEXT = (
    "I could not find sufficient evidence in the indexed documents to answer this question."
)


@dataclass
class GenerationResult:
    answer: str
    confidence: str
    sources: list[RetrievedChunk]
    context_tokens: int
    retrieved_count: int
    selected_count: int
    generation_latency_ms: float


def generate_answer(
    question: str,
    retrieved: list[RetrievedChunk],
    llm_client: LLMClient,
    settings: Settings,
) -> GenerationResult:
    if not retrieved or retrieved[0].score < settings.grounding_confidence_threshold:
        return GenerationResult(
            answer=ABSTENTION_TEXT,
            confidence="abstained",
            sources=[],
            context_tokens=0,
            retrieved_count=len(retrieved),
            selected_count=0,
            generation_latency_ms=0.0,
        )

    context = build_context(retrieved)
    user_prompt = build_user_prompt(question, context.chunks)

    start = time.perf_counter()
    answer = llm_client.complete(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    confidence = "high" if context.chunks[0].score >= 0.6 else "low"
    return GenerationResult(
        answer=answer,
        confidence=confidence,
        sources=context.chunks,
        context_tokens=context.total_tokens,
        retrieved_count=len(retrieved),
        selected_count=len(context.chunks),
        generation_latency_ms=elapsed_ms,
    )
