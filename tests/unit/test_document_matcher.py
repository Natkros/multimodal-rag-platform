from __future__ import annotations

from app.services.query_intelligence.document_matcher import find_mentioned_document


def test_finds_document_mentioned_by_descriptive_name():
    documents = [
        ("doc-1", "acme_vendor_security_policy.docx"),
        ("doc-2", "acme_employee_handbook.md"),
    ]
    result = find_mentioned_document("In the vendor security policy, what is the Tier 1 requirement?", documents)
    assert result == "doc-1"


def test_finds_document_via_handbook_reference():
    documents = [
        ("doc-1", "acme_vendor_security_policy.docx"),
        ("doc-2", "acme_employee_handbook.md"),
    ]
    result = find_mentioned_document("What does the employee handbook say about PTO?", documents)
    assert result == "doc-2"


def test_no_match_returns_none():
    documents = [("doc-1", "acme_vendor_security_policy.docx")]
    result = find_mentioned_document("What is the capital of France?", documents)
    assert result is None


def test_empty_document_list_returns_none():
    assert find_mentioned_document("What is the vendor policy?", []) is None


def test_weak_single_word_overlap_does_not_match():
    documents = [("doc-1", "acme_quarterly_revenue_chart.png")]
    # "revenue" alone overlapping a longer filename shouldn't be enough (needs >=2).
    result = find_mentioned_document("What was the revenue last year?", documents)
    assert result is None


def test_question_with_no_significant_words_returns_none():
    documents = [("doc-1", "acme_vendor_security_policy.docx")]
    result = find_mentioned_document("the a an", documents)
    assert result is None


def test_document_with_filename_of_only_stopwords_is_skipped():
    documents = [("doc-1", "the_report.pdf"), ("doc-2", "acme_vendor_security_policy.docx")]
    result = find_mentioned_document("What does the vendor security policy say?", documents)
    assert result == "doc-2"


def test_picks_best_match_among_multiple_candidates():
    documents = [
        ("doc-1", "acme_vendor_security_policy.docx"),
        ("doc-2", "acme_employee_handbook.md"),
        ("doc-3", "roomwise_product_faq.html"),
    ]
    result = find_mentioned_document("What does the product FAQ say about pricing?", documents)
    assert result == "doc-3"
