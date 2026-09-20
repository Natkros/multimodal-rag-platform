from __future__ import annotations

import io

import pytest
from docx import Document as DocxDocument
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.services.extraction.loaders import (
    CorruptedFileError,
    UnsupportedFileTypeError,
    extract,
    render_table_markdown,
)
from app.services.extraction.ocr import is_ocr_available


def _docx_bytes(paragraphs: list[tuple[str, str | None]]) -> bytes:
    doc = DocxDocument()
    for text, style in paragraphs:
        p = doc.add_paragraph(text)
        if style:
            p.style = doc.styles[style]
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _png_bytes(width=64, height=32, color="blue") -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_with_text(text: str, width=500, height=120) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((15, 40), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_docx_preserves_headings_as_markdown():
    raw = _docx_bytes([("Policy Overview", "Heading 1"), ("Some body text.", None)])
    result = extract("docx", raw)
    assert result.pages[0].text.startswith("# Policy Overview")
    assert "Some body text." in result.pages[0].text


def test_extract_docx_tables_are_structured_not_flattened():
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
    assert "Tier 1" not in result.pages[0].text  # not flattened into body text
    assert len(result.tables) == 1
    assert result.tables[0].headers == ["Tier", "Requirement"]
    assert result.tables[0].rows == [["Tier 1", "SOC 2"]]


def test_extract_docx_with_only_a_table_and_no_paragraphs_does_not_raise():
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "A"
    table.rows[0].cells[1].text = "B"
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = "2"
    buf = io.BytesIO()
    doc.save(buf)

    result = extract("docx", buf.getvalue())
    assert result.pages == []
    assert len(result.tables) == 1


def test_render_table_markdown():
    from app.services.extraction.loaders import ExtractedTable

    table = ExtractedTable(page=1, headers=["A", "B"], rows=[["1", "2"]])
    rendered = render_table_markdown(table)
    assert rendered == "| A | B |\n|---|---|\n| 1 | 2 |"


def test_extract_docx_empty_raises_corrupted():
    raw = _docx_bytes([])
    with pytest.raises(CorruptedFileError):
        extract("docx", raw)


def test_extract_docx_garbage_bytes_raises_corrupted():
    with pytest.raises(CorruptedFileError):
        extract("docx", b"not a real docx file")


def _zip_bytes_with_high_ratio_entry() -> bytes:
    """A minimal zip whose one entry is highly compressible (all zero bytes) —
    real decompression bombs use exactly this trick: a tiny compressed payload
    that expands enormously, since a run of identical bytes compresses to almost
    nothing under DEFLATE."""
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"\x00" * 50_000_000)
    return buf.getvalue()


def test_extract_docx_rejects_zip_with_extreme_compression_ratio():
    raw = _zip_bytes_with_high_ratio_entry()
    with pytest.raises(CorruptedFileError, match="expansion ratio"):
        extract("docx", raw)


def test_extract_docx_rejects_zip_exceeding_uncompressed_size_cap():
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        # Many small, low-ratio entries whose *total* declared size still exceeds
        # the cap - proves the guard checks the running total, not just one entry.
        for i in range(4):
            zf.writestr(f"part_{i}.bin", b"AB" * 40_000_000)  # ~80MB each, low ratio
    raw = buf.getvalue()
    with pytest.raises(CorruptedFileError, match="uncompressed size"):
        extract("docx", raw)


def test_extract_docx_normal_file_is_unaffected_by_zip_bomb_guard():
    """A real, ordinary .docx has a normal compression ratio and total size -
    confirms the guard doesn't false-positive on legitimate documents."""
    raw = _docx_bytes([("Ordinary paragraph text.", None)])
    result = extract("docx", raw)
    assert "Ordinary paragraph text." in result.pages[0].text


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


def test_extract_image_with_no_text_stays_visual_only():
    result = extract("image", _png_bytes(width=100, height=50))
    assert result.is_visual_only is True
    assert result.pages == []
    assert result.metadata["image_width"] == 100
    assert result.metadata["image_height"] == 50
    assert result.metadata["image_format"] == "PNG"
    assert result.metadata["ocr_used"] is False


@pytest.mark.skipif(not is_ocr_available(get_settings()), reason="Tesseract not installed")
def test_extract_image_with_text_is_ocrd():
    result = extract("image", _png_with_text("Quarterly Revenue Report 2025"))
    assert result.is_visual_only is False
    assert len(result.pages) == 1
    assert "revenue" in result.pages[0].text.lower() or "2025" in result.pages[0].text
    assert result.metadata["ocr_used"] is True


def test_extract_image_garbage_bytes_raises_corrupted():
    with pytest.raises(CorruptedFileError):
        extract("image", b"not an image")


def test_extract_unsupported_type_raises():
    with pytest.raises(UnsupportedFileTypeError):
        extract("zip", b"PK\x03\x04")


def _pdf_with_table() -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    data = [["Tier", "Requirement"], ["Tier 1", "SOC 2 Type II"], ["Tier 2", "Documented policy"]]
    table = Table(data)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    doc.build([table])
    return buf.getvalue()


def _scanned_pdf() -> bytes:
    """A PDF whose only content is an embedded image — no real text layer, like a
    scanned document."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    image_bytes = _png_with_text("Scanned invoice number 4471")
    img_path_buf = io.BytesIO(image_bytes)
    from PIL import Image as PILImage

    img = PILImage.open(img_path_buf)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawInlineImage(img, 50, 500, width=400, height=96)
    c.save()
    return buf.getvalue()


def test_extract_pdf_detects_structured_table():
    result = extract("pdf", _pdf_with_table())
    assert len(result.tables) == 1
    assert result.tables[0].headers == ["Tier", "Requirement"]
    assert ["Tier 1", "SOC 2 Type II"] in result.tables[0].rows


@pytest.mark.skipif(not is_ocr_available(get_settings()), reason="Tesseract/Poppler not installed")
def test_extract_scanned_pdf_falls_back_to_ocr():
    result = extract("pdf", _scanned_pdf())
    assert result.metadata.get("ocr_used") is True
    assert len(result.pages) == 1
    assert result.pages[0].text.strip() != ""


def test_extract_pdf_with_no_text_and_no_ocr_raises_corrupted(monkeypatch):
    import app.services.extraction.loaders as loaders_module

    monkeypatch.setattr(loaders_module, "ocr_pdf_pages", lambda raw, settings: [])
    with pytest.raises(CorruptedFileError):
        extract("pdf", _scanned_pdf())
