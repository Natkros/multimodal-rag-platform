"""Phase 8 query analysis: deterministic classification (ambiguous / short / multi-part
/ follow-up / document-specific) and lightweight entity extraction (years, quarters).

Deliberately not an LLM call — these are cheap, narrow structural signals (word count,
connective words, pronoun-without-antecedent patterns) that decide *whether* to spend
an LLM call on rewriting/decomposition downstream, not something that itself needs
language understanding. Same reasoning as Phase 5's query_classifier.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_MULTI_PART_KEYWORDS = (
    "compare", "versus", " vs ", " vs. ", "difference between", "both", "and explain",
)
_FOLLOW_UP_STARTERS = (
    "what about", "and what", "and how", "and why", "also,", "what else", "how about",
    "and the", "and its", "and their",
)
# Bare pronouns that need an antecedent to resolve — only a follow-up signal when
# conversation history actually exists (see classify_query).
_UNRESOLVED_PRONOUNS = (
    r"\bit\b", r"\bthis\b", r"\bthat\b", r"\bthey\b", r"\bthose\b", r"\bthese\b",
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_QUARTER_RE = re.compile(
    r"\bQ[1-4]\b|\b(first|second|third|fourth)\s+quarter\b", re.IGNORECASE
)


@dataclass
class QueryAnalysis:
    word_count: int
    is_short: bool
    is_ambiguous: bool
    is_multi_part: bool
    is_follow_up: bool
    mentioned_years: list[str] = field(default_factory=list)
    mentioned_quarters: list[str] = field(default_factory=list)


def extract_entities(question: str) -> tuple[list[str], list[str]]:
    # .finditer (not .findall) because _YEAR_RE has a capturing group for the century
    # prefix — .findall would return just that group ("19"/"20"), not the full year.
    years = [m.group(0) for m in _YEAR_RE.finditer(question)]
    quarters = [m.group(0) for m in _QUARTER_RE.finditer(question)]
    return years, quarters


def classify_query(question: str, has_history: bool, short_word_threshold: int = 4) -> QueryAnalysis:
    text = question.strip()
    words = text.split()
    word_count = len(words)
    lower = text.lower()

    is_short = 0 < word_count <= short_word_threshold

    is_multi_part = bool(text.count("?") > 1 or any(kw in lower for kw in _MULTI_PART_KEYWORDS))

    starts_with_follow_up = any(lower.startswith(s) for s in _FOLLOW_UP_STARTERS)
    has_unresolved_pronoun = any(re.search(p, lower) for p in _UNRESOLVED_PRONOUNS)
    is_follow_up = has_history and (starts_with_follow_up or (is_short and has_unresolved_pronoun))

    # Ambiguous: short and pronoun-referential with nothing to resolve against, or a
    # bare few-word fragment with no clear subject at all.
    is_ambiguous = (is_short and has_unresolved_pronoun and not has_history) or (
        is_short and not has_history and word_count <= 2
    )

    years, quarters = extract_entities(text)

    return QueryAnalysis(
        word_count=word_count,
        is_short=is_short,
        is_ambiguous=is_ambiguous,
        is_multi_part=is_multi_part,
        is_follow_up=is_follow_up,
        mentioned_years=years,
        mentioned_quarters=quarters,
    )
