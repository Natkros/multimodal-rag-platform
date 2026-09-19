from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.services.extraction.ocr import is_ocr_available, ocr_image_bytes, ocr_pdf_pages


def _png_with_text(text: str, width=500, height=120) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((15, 40), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_ocr_image_bytes_garbage_returns_empty_string_not_exception():
    settings = get_settings()
    assert ocr_image_bytes(b"not an image", settings) == ""


def test_ocr_disabled_returns_empty_string():
    settings = get_settings().model_copy(update={"ocr_enabled": False})
    result = ocr_image_bytes(_png_with_text("Should not be read"), settings)
    assert result == ""


def test_ocr_pdf_pages_disabled_returns_empty_list():
    settings = get_settings().model_copy(update={"ocr_enabled": False})
    assert ocr_pdf_pages(b"whatever", settings) == []


def test_ocr_pdf_pages_garbage_bytes_returns_empty_list_not_exception():
    settings = get_settings()
    assert ocr_pdf_pages(b"not a pdf", settings) == []


@pytest.mark.skipif(not is_ocr_available(get_settings()), reason="Tesseract not installed")
def test_ocr_image_bytes_finds_real_text():
    settings = get_settings()
    result = ocr_image_bytes(_png_with_text("Hello OCR World"), settings)
    assert "OCR" in result or "ocr" in result.lower()


@pytest.mark.skipif(not is_ocr_available(get_settings()), reason="Tesseract not installed")
def test_is_ocr_available_respects_bad_cmd_path():
    settings = get_settings().model_copy(update={"ocr_tesseract_cmd": "/nonexistent/tesseract"})
    assert is_ocr_available(settings) is False
