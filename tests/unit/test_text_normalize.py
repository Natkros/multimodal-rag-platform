from __future__ import annotations

from app.utils.text_normalize import normalize_text


def test_normalize_converts_crlf_to_lf():
    assert normalize_text("line1\r\nline2\r\n") == "line1\nline2"


def test_normalize_collapses_excess_blank_lines():
    assert normalize_text("a\n\n\n\n\nb") == "a\n\nb"


def test_normalize_strips_trailing_whitespace_per_line():
    assert normalize_text("hello   \nworld") == "hello\nworld"


def test_normalize_strips_leading_trailing_whitespace_overall():
    assert normalize_text("  \n\n hello \n\n  ") == "hello"


def test_normalize_is_idempotent():
    text = "Some text.\r\n\r\n\r\nMore text.   \n"
    once = normalize_text(text)
    twice = normalize_text(once)
    assert once == twice
