"""OCR wrapper around Tesseract (via pytesseract) and PDF page rendering (via
pdf2image/Poppler). Both are system binaries, not pip packages — see
docs/decisions/0004-phase4-multimodal-processing.md for install instructions.

Every function here degrades gracefully: if the binaries aren't installed, or OCR
fails on a specific image, callers get an empty string back, not an exception. OCR is
a best-effort enhancement over the base extraction, not something ingestion should
fail on.
"""
from __future__ import annotations

import logging

from app.core.config import Settings

logger = logging.getLogger(__name__)


class OCRUnavailableError(RuntimeError):
    pass


def _configure_tesseract(settings: Settings) -> None:
    import pytesseract

    if settings.ocr_tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.ocr_tesseract_cmd


def is_ocr_available(settings: Settings) -> bool:
    if not settings.ocr_enabled:
        return False
    try:
        import pytesseract

        _configure_tesseract(settings)
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_image_bytes(raw_bytes: bytes, settings: Settings) -> str:
    """Returns extracted text, or "" if OCR is unavailable/fails — never raises."""
    if not settings.ocr_enabled:
        return ""
    try:
        import io

        import pytesseract
        from PIL import Image

        _configure_tesseract(settings)
        with Image.open(io.BytesIO(raw_bytes)) as img:
            return pytesseract.image_to_string(img).strip()
    except Exception:
        logger.warning("OCR failed for image", exc_info=True)
        return ""


def ocr_pdf_pages(raw_bytes: bytes, settings: Settings) -> list[str]:
    """Renders each PDF page to an image and OCRs it. Returns one string per page, in
    order; returns [] if OCR/Poppler is unavailable or rendering fails."""
    if not settings.ocr_enabled:
        return []
    try:
        import pytesseract
        from pdf2image import convert_from_bytes

        _configure_tesseract(settings)
        images = convert_from_bytes(raw_bytes, poppler_path=settings.ocr_poppler_path)
        return [pytesseract.image_to_string(img).strip() for img in images]
    except Exception:
        logger.warning("OCR fallback failed for scanned PDF", exc_info=True)
        return []
