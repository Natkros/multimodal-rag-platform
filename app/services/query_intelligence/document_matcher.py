"""Detects when a question names a specific indexed document
("In the vendor security policy, what is...") so retrieval can auto-scope to it —
deterministic substring matching against filenames, not an LLM call, since this is
just "does this word sequence appear in that word sequence."

Only used when the caller didn't already pass explicit `document_ids` — an explicit
filter always wins over an inferred one.
"""
from __future__ import annotations

import re

_STOPWORDS = {"the", "a", "an", "document", "file", "policy", "report", "pdf", "doc", "docx"}


def _normalize(name: str) -> str:
    name = re.sub(r"\.[a-zA-Z0-9]+$", "", name)  # strip extension
    name = re.sub(r"[_\-]+", " ", name)
    return name.lower().strip()


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def find_mentioned_document(question: str, documents: list[tuple[str, str]]) -> str | None:
    """`documents` is a list of (document_id, filename). Returns the document_id whose
    filename's significant words overlap the question the most, if that overlap is
    strong enough to be a real signal (at least 2 matching words, or 1 for a short
    filename) — otherwise None."""
    question_words = _significant_words(question)
    if not question_words:
        return None

    best_id: str | None = None
    best_overlap = 0
    for document_id, filename in documents:
        doc_words = _significant_words(_normalize(filename))
        if not doc_words:
            continue
        overlap = len(question_words & doc_words)
        required = 1 if len(doc_words) <= 2 else 2
        if overlap >= required and overlap > best_overlap:
            best_overlap = overlap
            best_id = document_id

    return best_id
