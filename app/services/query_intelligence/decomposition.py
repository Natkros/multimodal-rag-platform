"""Decomposes a multi-part question into independently-retrievable sub-questions, via
an LLM call — e.g. "Compare revenue growth between 2023 and 2024 and explain the
primary drivers" -> ["What was the revenue in 2023?", "What was the revenue in
2024?", "What drove revenue growth?"]. Each sub-question is retrieved separately
(app/api/routes/query.py tracks every retrieval operation, per the project brief), and
the merged evidence is handed to generation once, so the final answer still
synthesizes across sub-questions in one pass rather than three separate answers.

Fails soft: an unconfigured or failing LLM returns [] (the caller falls back to
retrieving the original question as a single query, not a failure).
"""
from __future__ import annotations

import logging

from app.services.generation.llm_client import LLMClient

logger = logging.getLogger(__name__)

DECOMPOSE_SYSTEM_PROMPT = """You break a multi-part question into 2-4 independent \
sub-questions, each answerable by retrieving one focused piece of evidence.

Rules:
1. Output ONLY the sub-questions, one per line, no numbering, no preamble.
2. Each sub-question must be a complete, self-contained question.
3. Do not answer the sub-questions — only generate them.
4. If the question is already a single, focused question, output it unchanged as the \
only line."""


def decompose_query(question: str, llm_client: LLMClient, max_tokens: int = 300) -> list[str]:
    try:
        response = llm_client.complete(
            system=DECOMPOSE_SYSTEM_PROMPT,
            user=f"Question: {question}\n\nSub-questions:",
            max_tokens=max_tokens,
            temperature=0.0,
        )
        sub_questions = [line.strip("- ").strip() for line in response.strip().splitlines()]
        sub_questions = [q for q in sub_questions if q]
        # A single unchanged line back means the model judged it non-decomposable —
        # let the caller treat that the same as "decomposition found nothing to do".
        if len(sub_questions) <= 1:
            return []
        return sub_questions
    except Exception:
        logger.warning("Query decomposition failed; falling back to single query", exc_info=True)
        return []
