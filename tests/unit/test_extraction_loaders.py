from __future__ import annotations

import io

import pytest
from docx import Document as DocxDocument
from PIL import Image

from app.services.extraction.loaders import (
    CorruptedFileError,
    UnsupportedFileTypeError,
    extract,
)


def _docx_bytes(paragraphs: list[tuple[str, str | None]]) -> bytes:
    doc = DocxDocument()
    for text, style in paragraphs:
        p = doc.add_paragraph(text)
        if style:
            p.style = doc.styles[style]
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _png_bytes(width=64, height=32) -> bytes:
    img = Image.new("RGB", (width, height), "blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_docx_preserves_headings_as_markdown():
    raw = _docx_bytes([("Policy Overview", "Heading 1"), ("Some body text.", None)])
    result = extract("docx", raw)
    assert result.pages[0].text.startswith("# Policy Overview")
    assert "Some body text." in result.pages[0].text


def test_extract_docx_flattens_tables():
    doc = DocxDocument()
    doc.add_paragraph("Intro paragraph.")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Tier"
    table.rows[0].cells[1].text = "Requirement"
    row = table.add_row()
    row.cells[0].text = "Tier 1"
    row.cells[1].text = "SOC 2"
    buf = io.BytesIO()
    doc.save(buf)

    result = extract("docx", buf.getvalue())
    assert "Tier 1 | SOC 2" in result.pages[0].text


def test_extract_docx_empty_raises_corrupted():
    raw = _docx_bytes([])
    with pytest.raises(CorruptedFileError):
        extract("docx", raw)


def test_extract_docx_garbage_bytes_raises_corrupted():
    with pytest.raises(CorruptedFileError):
        extract("docx", b"not a real docx file")


def test_extract_docx_captures_core_properties():
    doc = DocxDocument()
    doc.core_properties.title = "My Title"
    doc.core_properties.author = "Jane Doe"
    doc.add_paragraph("Body text.")
    buf = io.BytesIO()
    doc.save(buf)

    result = extract("docx", buf.getvalue())
    assert result.metadata["title"] == "My Title"
    assert result.metadata["author"] == "Jane Doe"


def test_extract_html_preserves_headings_and_strips_scripts():
    html = (
        b"<html><head><title>T</title></head><body>"
        b"<script>alert('x')</script>"
        b"<h1>Main Title</h1><p>First paragraph.</p>"
        b"<h2>Sub Section</h2><p>Second paragraph.</p>"
        b"</body></html>"
    )
    result = extract("html", html)
    text = result.pages[0].text
    assert "# Main Title" in text
    assert "## Sub Section" in text
    assert "alert" not in text
    assert result.metadata["title"] == "T"


def test_extract_html_empty_raises_corrupted():
    with pytest.raises(CorruptedFileError):
        extract("html", b"<html><body></body></html>")


def test_extract_image_returns_visual_only_with_dimensions():
    result = extract("image", _png_bytes(width=100, height=50))
    assert result.is_visual_only is True
    assert result.pages == []
    assert result.metadata["image_width"] == 100
    assert result.metadata["image_height"] == 50
    assert result.metadata["image_format"] == "PNG"


def test_extract_image_garbage_bytes_raises_corrupted():
    with pytest.raises(CorruptedFileError):
        extract("image", b"not an image")


def test_extract_unsupported_type_raises():
    with pytest.raises(UnsupportedFileTypeError):
        extract("zip", b"PK\x03\x04")
