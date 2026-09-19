"""Follow-up query rewriting: turns "What about the second quarter?" into a
self-contained question using the last few conversation turns, via an LLM call.

Fails soft, like app/services/generation/vision_describer.py: an unconfigured or
failing LLM returns the original question unchanged rather than failing the request —
a follow-up query that doesn't get rewritten just retrieves less precisely, which is
strictly better than a 500.
"""
from __future__ import annotations

import logging

from app.services.generation.llm_client import LLMClient

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = """You rewrite a follow-up question into a single, fully \
self-contained question, using the conversation history to resolve pronouns and \
implicit references (e.g. "it", "that", "the second quarter" meaning which year).

Rules:
1. Output ONLY the rewritten question — no preamble, no quotes, no explanation.
2. Preserve the user's intent exactly; do not answer the question or add information.
3. If the follow-up is already self-contained, return it unchanged.
4. Resolve references using the most recent relevant turn in the history."""


def rewrite_follow_up(
    question: str, history: list[tuple[str, str]], llm_client: LLMClient, max_tokens: int = 200
) -> str:
    if not history:
        return question

    history_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in history)
    user_prompt = f"Conversation history:\n{history_text}\n\nFollow-up question: {question}\n\nRewritten question:"

    try:
        rewritten = llm_client.complete(
            system=REWRITE_SYSTEM_PROMPT, user=user_prompt, max_tokens=max_tokens, temperature=0.0
        )
        rewritten = rewritten.strip().strip('"')
        return rewritten or question
    except Exception:
        logger.warning("Query rewrite failed; falling back to original question", exc_info=True)
        return question
