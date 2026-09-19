from __future__ import annotations

from app.services.retrieval.query_classifier import classify_query_content_types


def test_classifies_chart_question_as_image():
    result = classify_query_content_types("What was the revenue shown in the chart on page 14?")
    assert result == {"image"}


def test_classifies_diagram_question_as_image():
    assert classify_query_content_types("What does the architecture diagram indicate?") == {"image"}


def test_classifies_table_comparison_as_table():
    assert classify_query_content_types("Compare the two tables.") == {"table"}


def test_classifies_row_column_wording_as_table():
    assert classify_query_content_types("What's in the second row of that spreadsheet?") == {"table"}


def test_classifies_document_says_wording_as_text():
    result = classify_query_content_types("The document says X. Where is the evidence?")
    assert result == {"text"}


def test_generic_question_has_no_restriction():
    assert classify_query_content_types("What is Acme's cancellation policy?") == set()


def test_empty_question_has_no_restriction():
    assert classify_query_content_types("") == set()


def test_matches_both_image_and_table_keywords():
    result = classify_query_content_types("Does the chart match the numbers in the table?")
    assert result == {"image", "table"}


def test_is_case_insensitive():
    assert classify_query_content_types("SHOW ME THE CHART") == {"image"}


def test_word_boundary_avoids_false_positive_substring_match():
    # "table" is a substring of "portable" but must not match as a standalone word
    assert classify_query_content_types("Is the deployment portable across environments?") == set()
