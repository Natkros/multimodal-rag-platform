from __future__ import annotations

from app.services.generation.citation_validator import parse_cited_sentences, validate_citations


def test_parse_single_sentence_single_citation():
    result = parse_cited_sentences("Acme's Q2 revenue was $42.3 million [1].")
    assert result == [("Acme's Q2 revenue was $42.3 million.", [1])]


def test_parse_multiple_sentences_multiple_citations():
    text = "Acme was founded in 2010 [1]. It moved headquarters in 2015 [2]."
    result = parse_cited_sentences(text)
    assert result == [
        ("Acme was founded in 2010.", [1]),
        ("It moved headquarters in 2015.", [2]),
    ]


def test_parse_sentence_with_multiple_citation_markers():
    result = parse_cited_sentences("Revenue grew across both segments [1][2].")
    assert result[0][1] == [1, 2]


def test_parse_sentence_with_no_citation_is_skipped():
    text = "This has no citation. This one does [1]."
    result = parse_cited_sentences(text)
    assert len(result) == 1
    assert result[0][1] == [1]


def test_validate_supported_claim_with_matching_number():
    answer = "Acme's Q2 2025 revenue was $42.3 million [1]."
    sources = ["Acme's Q2 2025 revenue was $42.3 million, up 18% year over year."]
    result = validate_citations(answer, sources)
    assert result.total_claims == 1
    assert result.supported_claims == 1
    assert result.citation_correctness == 1.0


def test_validate_unsupported_claim_with_fabricated_number():
    answer = "Acme's Q2 2025 revenue was $99.9 million [1]."
    sources = ["Acme's Q2 2025 revenue was $42.3 million, up 18% year over year."]
    result = validate_citations(answer, sources)
    assert result.supported_claims == 0
    assert result.citation_correctness == 0.0
    assert "$99.9" in result.unsupported_claims[0].missing_numbers


def test_validate_unsupported_claim_with_low_word_overlap():
    answer = "Acme discontinued its entire product line and filed for bankruptcy [1]."
    sources = ["Acme's Q2 2025 revenue was $42.3 million, up 18% year over year."]
    result = validate_citations(answer, sources)
    assert result.supported_claims == 0


def test_validate_no_citations_returns_none_correctness():
    result = validate_citations("This answer has no citations at all.", ["Some source text."])
    assert result.total_claims == 0
    assert result.citation_correctness is None


def test_validate_citation_number_out_of_range_treated_as_unsupported():
    answer = "Something was claimed [5]."
    result = validate_citations(answer, ["Only one source."])
    assert result.supported_claims == 0


def test_validate_catches_fabricated_proper_noun_despite_high_word_overlap():
    """Regression: high generic word-overlap ("company", "founded") must not mask a
    fabricated distinctive claim (a place name absent from the source)."""
    answer = "The company was founded on Mars [1]."
    sources = ["The company was founded in Austin, Texas in 2010."]
    result = validate_citations(answer, sources)
    assert result.supported_claims == 0
    assert "Mars" in result.claims[0].missing_proper_nouns


def test_validate_multiple_claims_mixed_support():
    answer = "Q2 revenue was $42.3 million [1]. The company was founded on Mars [2]."
    sources = [
        "Q2 revenue was $42.3 million.",
        "The company was founded in Austin, Texas in 2010.",
    ]
    result = validate_citations(answer, sources)
    assert result.total_claims == 2
    assert result.supported_claims == 1
    assert result.citation_correctness == 0.5
