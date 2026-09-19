"""Content extraction for Phase 2 file types (PDF, TXT, Markdown, DOCX, HTML, images).

Returns an `ExtractionResult` — a unified representation the chunker consumes
regardless of source format. HTML and DOCX are normalized into the same
heading-marked plain text the Markdown chunker already understands (headings become
`#`..`######` lines) rather than teaching the chunker format-specific structure.

Images carry no extractable text yet (`is_visual_only=True`): OCR and visual
description are Phase 4/5 scope. Phase 2 still catalogs them — format, dimensions,
and other metadata are extracted and stored — but `pages` is empty and the ingestion
pipeline skips chunking/embedding for them rather than pretending to index unsearchable
content.
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
    is_visual_only: bool = False


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
    if file_type == "docx":
        return _extract_docx(raw_bytes)
    if file_type == "html":
        return _extract_html(raw_bytes)
    if file_type == "image":
        return _extract_image(raw_bytes)
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


def _extract_docx(raw_bytes: bytes) -> ExtractionResult:
    import io
    import zipfile

    from docx import Document as DocxDocument
    from docx.opc.exceptions import PackageNotFoundError

    try:
        docx_doc = DocxDocument(io.BytesIO(raw_bytes))
    except (PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise CorruptedFileError(f"Could not parse DOCX: {exc}") from exc

    lines: list[str] = []
    for paragraph in docx_doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = (paragraph.style.name if paragraph.style else "") or ""
        if style_name.startswith("Heading"):
            level = "".join(ch for ch in style_name if ch.isdigit()) or "1"
            level = min(int(level), 6)
            lines.append(f"{'#' * level} {text}")
        elif style_name == "Title":
            lines.append(f"# {text}")
        else:
            lines.append(text)

    # Tables have no structured extraction yet (Phase 4) — flattened as pipe-delimited
    # rows so their content is at least searchable, not silently dropped.
    for table in docx_doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))

    full_text = "\n\n".join(lines)
    if not full_text.strip():
        raise CorruptedFileError("DOCX has no extractable text content")

    props = docx_doc.core_properties
    metadata = {"title": props.title or None, "author": props.author or None}
    return ExtractionResult(pages=[ExtractedPage(page_number=1, text=full_text)], page_count=1, metadata=metadata)


def _extract_html(raw_bytes: bytes) -> ExtractionResult:
    from bs4 import BeautifulSoup

    html_text = _decode(raw_bytes)
    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else None

    body = soup.body or soup
    lines: list[str] = []
    heading_tags = {f"h{i}" for i in range(1, 7)}
    for element in body.find_all(list(heading_tags | {"p", "li", "td", "th"})):
        text = " ".join(element.get_text(" ", strip=True).split())
        if not text:
            continue
        if element.name in heading_tags:
            level = int(element.name[1])
            lines.append(f"{'#' * level} {text}")
        else:
            lines.append(text)

    full_text = "\n\n".join(lines)
    if not full_text.strip():
        raise CorruptedFileError("HTML has no extractable text content")

    return ExtractionResult(
        pages=[ExtractedPage(page_number=1, text=full_text)], page_count=1, metadata={"title": title}
    )


def _extract_image(raw_bytes: bytes) -> ExtractionResult:
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            width, height = img.size
            image_format = img.format
    except UnidentifiedImageError as exc:
        raise CorruptedFileError(f"Could not parse image: {exc}") from exc

    return ExtractionResult(
        pages=[],
        page_count=1,
        metadata={
            "image_width": width,
            "image_height": height,
            "image_format": image_format,
            "text_extraction": "pending_multimodal_processing",
        },
        is_visual_only=True,
    )
