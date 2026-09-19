"""Phase 11 citation validation: does a cited chunk actually support the sentence it's
attached to? Deterministic (word-overlap + exact-number matching), not an LLM-as-judge
call — this is the "citation correctness [deterministic]" metric already named in
docs/evaluation.md, and per this project's engineering rules, a metric only ships once
its computation method is decided and stated, not left as a vague "trust the model"
claim.

Numbers get special treatment: a sentence claiming "$42.3 million" is falsifiable in a
way "revenue grew" isn't — if the sentence contains a number/percentage/dollar amount
that never appears in the cited chunk, that's treated as unsupported regardless of how
much surrounding word overlap there is, since a plausible-sounding sentence with a
fabricated number is exactly the failure mode citation validation exists to catch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"])')
_CITATION_RE = re.compile(r"\s*\[(\d+)\]")
_TRAILING_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,!?])")
_NUMBER_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
# Capitalized words other than the sentence's own first word — candidate proper nouns
# (names, places) whose presence should be independently verifiable in the source,
# the same reasoning as numbers: a fabricated name is a distinctive, falsifiable claim
# that generic word-overlap can miss if the rest of the sentence overlaps heavily.
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "to", "of",
    "in", "on", "at", "for", "and", "or", "but", "with", "as", "by", "that", "this",
    "it", "its", "from", "has", "have", "had", "will", "would", "based", "above",
}


@dataclass
class CitedClaim:
    sentence: str
    citation_numbers: list[int]
    supported: bool
    overlap_ratio: float
    missing_numbers: list[str]
    missing_proper_nouns: list[str] = field(default_factory=list)


@dataclass
class CitationValidationResult:
    claims: list[CitedClaim]

    @property
    def total_claims(self) -> int:
        return len(self.claims)

    @property
    def supported_claims(self) -> int:
        return sum(1 for c in self.claims if c.supported)

    @property
    def citation_correctness(self) -> float | None:
        """None (not 0.0) when there were no cited claims to check — an answer with
        zero citations isn't "0% correct," it's simply not applicable."""
        if not self.claims:
            return None
        return self.supported_claims / self.total_claims

    @property
    def unsupported_claims(self) -> list[CitedClaim]:
        return [c for c in self.claims if not c.supported]


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def parse_cited_sentences(answer_text: str) -> list[tuple[str, list[int]]]:
    """Splits the answer into sentences and pairs each with the citation numbers it
    references. Sentences with no citation marker are skipped — nothing to validate."""
    sentences = _SENTENCE_RE.split(answer_text.strip())
    result = []
    for sentence in sentences:
        numbers = [int(n) for n in _CITATION_RE.findall(sentence)]
        if not numbers:
            continue
        clean = _CITATION_RE.sub("", sentence).strip()
        clean = _TRAILING_SPACE_BEFORE_PUNCT_RE.sub(r"\1", clean)
        if clean:
            result.append((clean, numbers))
    return result


def _check_claim(sentence: str, source_texts: list[str], overlap_threshold: float) -> CitedClaim:
    combined_source = " ".join(source_texts)
    combined_source_lower = combined_source.lower()
    sentence_tokens = _tokenize(sentence)
    source_tokens = _tokenize(combined_source)

    overlap_ratio = (
        len(sentence_tokens & source_tokens) / len(sentence_tokens) if sentence_tokens else 1.0
    )

    sentence_numbers = _NUMBER_RE.findall(sentence)
    missing_numbers = [n for n in sentence_numbers if n not in combined_source]

    # Proper nouns other than the sentence's own first word (which is capitalized
    # regardless of what it is) — a name/place introduced here but absent from every
    # cited source is exactly the kind of fabrication generic word overlap can miss.
    proper_nouns = [m for m in _PROPER_NOUN_RE.finditer(sentence) if m.start() != 0]
    missing_proper_nouns = [
        m.group(0) for m in proper_nouns if m.group(0).lower() not in combined_source_lower
    ]

    supported = overlap_ratio >= overlap_threshold and not missing_numbers and not missing_proper_nouns

    return CitedClaim(
        sentence=sentence,
        citation_numbers=[],  # filled by caller, which has the numbers already
        supported=supported,
        overlap_ratio=round(overlap_ratio, 3),
        missing_numbers=missing_numbers,
        missing_proper_nouns=missing_proper_nouns,
    )


def validate_citations(
    answer_text: str, numbered_sources: list[str], overlap_threshold: float = 0.5
) -> CitationValidationResult:
    """`numbered_sources` is source text indexed by citation number - 1 (i.e.
    `numbered_sources[0]` is what `[1]` refers to), matching the numbering
    `app/services/generation/prompt.py`'s context block uses."""
    claims = []
    for sentence, citation_numbers in parse_cited_sentences(answer_text):
        cited_texts = [
            numbered_sources[n - 1] for n in citation_numbers if 0 < n <= len(numbered_sources)
        ]
        claim = _check_claim(sentence, cited_texts, overlap_threshold)
        claim.citation_numbers = citation_numbers
        claims.append(claim)
    return CitationValidationResult(claims=claims)
