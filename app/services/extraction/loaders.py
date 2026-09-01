"""Content extraction for Phase 1 file types (PDF, TXT, Markdown).

Returns a `ExtractedPage` list — a unified representation that later phases (DOCX,
HTML, OCR, table/image extraction) extend without changing the chunker's input shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pypdf import PdfReader


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    section: str | None = None


@dataclass
class ExtractionResult:
    pages: list[ExtractedPage]
    page_count: int
    metadata: dict = field(default_factory=dict)


class UnsupportedFileTypeError(ValueError):
    pass


class CorruptedFileError(ValueError):
    pass


def extract(file_type: str, raw_bytes: bytes) -> ExtractionResult:
    if file_type == "pdf":
        return _extract_pdf(raw_bytes)
    if file_type == "txt":
        return _extract_plain_text(raw_bytes)
    if file_type == "markdown":
        return _extract_markdown(raw_bytes)
    raise UnsupportedFileTypeError(f"No extractor registered for file_type={file_type!r}")


def _decode(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CorruptedFileError("Could not decode file as text")


def _extract_pdf(raw_bytes: bytes) -> ExtractionResult:
    import io

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except Exception as exc:  # pypdf raises various errors for malformed PDFs
        raise CorruptedFileError(f"Could not parse PDF: {exc}") from exc

    if len(reader.pages) == 0:
        raise CorruptedFileError("PDF has no pages")

    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(ExtractedPage(page_number=i, text=text))

    doc_info = reader.metadata or {}
    return ExtractionResult(
        pages=pages,
        page_count=len(reader.pages),
        metadata={"title": getattr(doc_info, "title", None)},
    )


def _extract_plain_text(raw_bytes: bytes) -> ExtractionResult:
    text = _decode(raw_bytes)
    if not text.strip():
        raise CorruptedFileError("File is empty")
    return ExtractionResult(pages=[ExtractedPage(page_number=1, text=text)], page_count=1)


def _extract_markdown(raw_bytes: bytes) -> ExtractionResult:
    text = _decode(raw_bytes)
    if not text.strip():
        raise CorruptedFileError("File is empty")
    # Markdown is treated as a single logical page; section headings are recovered
    # during chunking (structure-aware chunker splits on `#`/`##`).
    return ExtractionResult(pages=[ExtractedPage(page_number=1, text=text)], page_count=1)
