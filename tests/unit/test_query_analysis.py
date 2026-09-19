from __future__ import annotations

from app.services.query_intelligence.analysis import classify_query, extract_entities


def test_short_query_detected():
    result = classify_query("Q2 revenue?", has_history=False)
    assert result.is_short is True
    assert result.word_count == 2


def test_normal_length_query_not_short():
    result = classify_query("What is Acme's cancellation policy for annual plans?", has_history=False)
    assert result.is_short is False


def test_multi_part_detected_via_compare_keyword():
    result = classify_query(
        "Compare revenue growth between 2023 and 2024 and explain the primary drivers.",
        has_history=False,
    )
    assert result.is_multi_part is True


def test_multi_part_detected_via_multiple_question_marks():
    result = classify_query("What was the revenue? What drove the growth?", has_history=False)
    assert result.is_multi_part is True


def test_single_clause_question_not_multi_part():
    result = classify_query("What is Acme's cancellation policy?", has_history=False)
    assert result.is_multi_part is False


def test_follow_up_detected_with_starter_phrase_and_history():
    result = classify_query("What about the second quarter?", has_history=True)
    assert result.is_follow_up is True


def test_follow_up_not_detected_without_history():
    # Same wording, but nothing to resolve "the second quarter" against.
    result = classify_query("What about the second quarter?", has_history=True)
    assert result.is_follow_up is True
    result_no_history = classify_query("What about the second quarter?", has_history=False)
    assert result_no_history.is_follow_up is False


def test_follow_up_detected_via_short_pronoun_reference():
    result = classify_query("What about that?", has_history=True)
    assert result.is_follow_up is True


def test_ambiguous_pronoun_with_no_history_is_ambiguous():
    result = classify_query("What about that?", has_history=False)
    assert result.is_ambiguous is True


def test_ambiguous_bare_fragment_with_no_history():
    result = classify_query("revenue?", has_history=False)
    assert result.is_ambiguous is True


def test_clear_question_is_not_ambiguous():
    result = classify_query("What was Acme's Q2 2025 revenue?", has_history=False)
    assert result.is_ambiguous is False


def test_extract_entities_years():
    years, quarters = extract_entities("Compare 2023 and 2024 revenue.")
    assert years == ["2023", "2024"]
    assert quarters == []


def test_extract_entities_quarters_q_notation():
    years, quarters = extract_entities("What was Q2 revenue?")
    assert quarters == ["Q2"]


def test_extract_entities_quarters_written_out():
    years, quarters = extract_entities("What about the second quarter results?")
    assert quarters == ["second quarter"]


def test_extract_entities_none_present():
    years, quarters = extract_entities("What is the cancellation policy?")
    assert years == []
    assert quarters == []


def test_document_specific_wording_still_classifies_normally():
    # classify_query doesn't do document matching itself (that's document_matcher.py)
    # but shouldn't choke on document-referencing phrasing.
    result = classify_query("In the vendor security policy, what is the Tier 1 requirement?", has_history=False)
    assert result.is_ambiguous is False
