"""Phase 5 query classification: which chunk content_type(s) — text, table, image —
should retrieval prefer for a given question?

Deliberately simple and deterministic (keyword matching), not an LLM call: Phase 8
(query intelligence) is where rewriting/expansion/decomposition via an LLM belongs.
This only needs to answer one narrow question — "does the wording suggest the answer
lives in a table, an image/chart, prose, or could be any of them" — cheaply and
without an API call.

An empty result means "no signal either way" — the caller should search across all
content types unfiltered (the spec's "hybrid retrieval" mode). A non-empty result
routes to the spec's "text retrieval" / "table retrieval" / "image retrieval" modes.
"""
from __future__ import annotations

import re

_IMAGE_KEYWORDS = (
    "chart", "charts", "diagram", "diagrams", "image", "images", "picture", "pictures",
    "photo", "photos", "graph", "graphs", "figure", "figures", "screenshot", "screenshots",
    "visual", "visually", "illustration", "illustrations",
)
_TABLE_KEYWORDS = (
    "table", "tables", "row", "rows", "column", "columns", "spreadsheet", "spreadsheets",
    "tabular",
)
_TEXT_KEYWORDS = (
    "the document says", "the text says", "according to the document",
    "according to the text", "in the paragraph", "in writing", "in the text",
)


def _matches_any(question_lower: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(kw)}\b", question_lower) for kw in keywords)


def classify_query_content_types(question: str) -> set[str]:
    """Returns a subset of {"text", "table", "image"} the query's wording points to,
    or an empty set if there's no clear signal (search everything)."""
    question_lower = question.lower()
    targets: set[str] = set()

    if _matches_any(question_lower, _IMAGE_KEYWORDS):
        targets.add("image")
    if _matches_any(question_lower, _TABLE_KEYWORDS):
        targets.add("table")
    if _matches_any(question_lower, _TEXT_KEYWORDS):
        targets.add("text")

    # If every type matched, that's the same as no restriction — treat it as "any"
    # rather than a real filter (avoids a degenerate three-way merge that's
    # equivalent to unfiltered search anyway).
    if targets == {"text", "table", "image"}:
        return set()

    return targets
