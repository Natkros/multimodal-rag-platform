"""Query expansion: generates a few alternative phrasings of a question via an LLM
call, so retrieval runs for each variant and merges results — catching relevant chunks
that use different wording than the user's literal phrasing (synonyms, terminology
mismatches) without needing a full multi-query fusion architecture. Phase 26's
"multi-query retrieval" is the more general form of this idea (systematic RAG-Fusion
across many query variants with dedicated fusion); this is the narrow, single-query
version scoped for Phase 8.

Fails soft: an unconfigured or failing LLM returns [] (no expansion), same pattern as
the rest of this package.
"""
from __future__ import annotations

import logging

from app.services.generation.llm_client import LLMClient

logger = logging.getLogger(__name__)

EXPAND_SYSTEM_PROMPT = """You generate 2 alternative phrasings of a question that \
preserve its exact meaning but use different words or sentence structure — useful for \
finding documents that describe the same thing with different terminology.

Rules:
1. Output ONLY the alternative phrasings, one per line, no numbering, no preamble.
2. Do not change what is being asked.
3. Do not answer the question."""


def expand_query(question: str, llm_client: LLMClient, max_tokens: int = 150) -> list[str]:
    try:
        response = llm_client.complete(
            system=EXPAND_SYSTEM_PROMPT,
            user=f"Question: {question}\n\nAlternative phrasings:",
            max_tokens=max_tokens,
            temperature=0.3,
        )
        variants = [line.strip("- ").strip() for line in response.strip().splitlines()]
        return [v for v in variants if v and v.lower() != question.lower()]
    except Exception:
        logger.warning("Query expansion failed; proceeding without expansion", exc_info=True)
        return []
