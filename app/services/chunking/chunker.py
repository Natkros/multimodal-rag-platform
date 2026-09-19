"""Chunking strategies.

Three strategies, compared with measured metrics in Phase 3 (see
evaluation/reports/ and docs/decisions/0003-phase3-chunking-comparison.md):
`fixed` (naive token-windowed baseline), `recursive` (structure-aware, splits on
markdown headings/paragraphs — the default), and `semantic`
(app/services/chunking/semantic_chunker.py — splits on embedding-similarity drops
between sentences). All three preserve page/section metadata on every chunk — see
docs/db_schema.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.extraction.loaders import ExtractionResult

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_WORD_RE = re.compile(r"\S+")


@dataclass
class Chunk:
    chunk_index: int
    text: str
    page: int | None
    section: str | None
    content_type: str = "text"
    token_count: int = 0


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~4 chars/token) — good enough for budgeting
    without pulling in a model-specific tokenizer in the hot path."""
    return max(1, len(text) // 4)


def _split_into_words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def fixed_size_chunk(
    pages: list, chunk_size_tokens: int, overlap_tokens: int, **_kwargs
) -> list[Chunk]:
    """Naive baseline: chunk purely by token-estimated word count, ignoring structure.
    Accepts and ignores strategy-specific kwargs (e.g. `embedder`) other strategies use,
    so `chunk_document` can call every strategy uniformly."""
    chunks: list[Chunk] = []
    index = 0
    words_per_chunk = chunk_size_tokens * 4  # ~4 chars/token, word-approx below
    for page in pages:
        words = _split_into_words(page.text)
        if not words:
            continue
        step = max(1, int(words_per_chunk * 0.75) - int(overlap_tokens * 0.75))
        window = max(1, int(words_per_chunk * 0.75))
        i = 0
        while i < len(words):
            piece = " ".join(words[i : i + window])
            if piece.strip():
                chunks.append(
                    Chunk(
                        chunk_index=index,
                        text=piece,
                        page=page.page_number,
                        section=None,
                        token_count=estimate_tokens(piece),
                    )
                )
                index += 1
            if i + window >= len(words):
                break
            i += step
    return chunks


def recursive_chunk(
    pages: list, chunk_size_tokens: int, overlap_tokens: int, **_kwargs
) -> list[Chunk]:
    """Structure-aware: split on markdown headings/paragraph boundaries first, then
    recursively pack paragraphs into token-budgeted windows with overlap, carrying the
    nearest heading as `section` metadata."""
    chunks: list[Chunk] = []
    index = 0
    max_chars = chunk_size_tokens * 4
    overlap_chars = overlap_tokens * 4

    for page in pages:
        segments = _split_by_structure(page.text)
        buffer = ""
        buffer_section: str | None = None
        current_section: str | None = None

        for section, paragraph in segments:
            if section is not None:
                current_section = section
            if not paragraph.strip():
                continue

            candidate = (buffer + "\n\n" + paragraph).strip() if buffer else paragraph
            if len(candidate) <= max_chars:
                buffer = candidate
                buffer_section = buffer_section or current_section
                continue

            if buffer:
                chunks.append(
                    Chunk(
                        chunk_index=index,
                        text=buffer,
                        page=page.page_number,
                        section=buffer_section,
                        token_count=estimate_tokens(buffer),
                    )
                )
                index += 1
                tail = buffer[-overlap_chars:] if overlap_chars > 0 else ""
                buffer = (tail + "\n\n" + paragraph).strip() if tail else paragraph
            else:
                buffer = paragraph
            buffer_section = current_section

            # A single paragraph longer than max_chars: hard-split it.
            while len(buffer) > max_chars:
                chunks.append(
                    Chunk(
                        chunk_index=index,
                        text=buffer[:max_chars],
                        page=page.page_number,
                        section=buffer_section,
                        token_count=estimate_tokens(buffer[:max_chars]),
                    )
                )
                index += 1
                buffer = buffer[max_chars - overlap_chars :]

        if buffer.strip():
            chunks.append(
                Chunk(
                    chunk_index=index,
                    text=buffer,
                    page=page.page_number,
                    section=buffer_section,
                    token_count=estimate_tokens(buffer),
                )
            )
            index += 1

    return chunks


def _split_by_structure(text: str) -> list[tuple[str | None, str]]:
    """Split text into (heading-or-None, paragraph) pairs. Markdown headings become the
    running `section`; otherwise splits on blank lines (paragraphs)."""
    result: list[tuple[str | None, str]] = []
    headings = list(_HEADING_RE.finditer(text))

    if not headings:
        for para in re.split(r"\n\s*\n", text):
            result.append((None, para.strip()))
        return result

    # Text before first heading
    if headings[0].start() > 0:
        preamble = text[: headings[0].start()].strip()
        if preamble:
            for para in re.split(r"\n\s*\n", preamble):
                result.append((None, para.strip()))

    for i, match in enumerate(headings):
        heading_text = match.group(2).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        first = True
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if not para:
                continue
            result.append((heading_text if first else None, para))
            first = False
        if first:
            # heading with no body paragraphs still marks the section
            result.append((heading_text, ""))

    return result


def _semantic_chunk(
    pages: list,
    chunk_size_tokens: int,
    overlap_tokens: int,
    embedder=None,
    similarity_threshold: float = 0.5,
    **_kwargs,
) -> list[Chunk]:
    from app.services.chunking.semantic_chunker import semantic_chunk

    return semantic_chunk(
        pages, chunk_size_tokens, overlap_tokens, embedder=embedder, similarity_threshold=similarity_threshold
    )


STRATEGIES = {
    "fixed": fixed_size_chunk,
    "recursive": recursive_chunk,
    "semantic": _semantic_chunk,
}


def chunk_document(
    extraction: ExtractionResult,
    strategy: str,
    chunk_size_tokens: int,
    overlap_tokens: int,
    embedder=None,
    similarity_threshold: float = 0.5,
) -> list[Chunk]:
    fn = STRATEGIES.get(strategy)
    if fn is None:
        raise ValueError(f"Unknown chunking strategy: {strategy!r}")
    return fn(
        extraction.pages,
        chunk_size_tokens,
        overlap_tokens,
        embedder=embedder,
        similarity_threshold=similarity_threshold,
    )
