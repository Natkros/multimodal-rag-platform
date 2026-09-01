from __future__ import annotations

from app.services.chunking.chunker import (
    estimate_tokens,
    fixed_size_chunk,
    recursive_chunk,
)
from app.services.extraction.loaders import ExtractedPage


def _page(text: str, page_number: int = 1) -> ExtractedPage:
    return ExtractedPage(page_number=page_number, text=text)


def test_estimate_tokens_monotonic():
    assert estimate_tokens("a" * 40) > estimate_tokens("a" * 4)


def test_recursive_chunk_preserves_headings():
    text = "# Intro\nSome intro text.\n\n## Details\n" + ("word " * 300)
    pages = [_page(text)]
    chunks = recursive_chunk(pages, chunk_size_tokens=100, overlap_tokens=10)
    assert len(chunks) >= 2
    sections = {c.section for c in chunks}
    assert "Intro" in sections or "Details" in sections


def test_recursive_chunk_no_content_loss_roughly():
    text = "word " * 500
    pages = [_page(text)]
    chunks = recursive_chunk(pages, chunk_size_tokens=50, overlap_tokens=5)
    joined_words = sum(len(c.text.split()) for c in chunks)
    # Overlap means joined word count should be >= original (never less -> no data loss)
    assert joined_words >= 500


def test_fixed_size_chunk_respects_page_boundaries():
    pages = [_page("word " * 100, page_number=1), _page("word " * 100, page_number=2)]
    chunks = fixed_size_chunk(pages, chunk_size_tokens=50, overlap_tokens=5)
    pages_seen = {c.page for c in chunks}
    assert pages_seen == {1, 2}


def test_empty_page_produces_no_chunks():
    pages = [_page("   \n\n  ")]
    chunks = recursive_chunk(pages, chunk_size_tokens=50, overlap_tokens=5)
    assert chunks == []
