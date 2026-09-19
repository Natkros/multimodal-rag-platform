"""Ingestion pipeline: extraction -> normalization -> chunking -> embedding -> indexing.

Runs synchronously inside a FastAPI BackgroundTask in Phase 1 (see
docs/decisions/0001-phase1-stack-choices.md for why, and the Phase 16 upgrade path).

Phase 4 multimodal handling:
- Tables (`extraction.tables`, from PDF/DOCX) become their own chunks
  (`content_type="table"`), appended after the document's regular text chunks, with
  headers/rows preserved verbatim in `Chunk.extra_metadata` — never flattened into
  body text (see app/services/extraction/loaders.py).
- Images bypass `chunk_document()` entirely and become at most ONE chunk
  (`content_type="image"`): OCR text (if Tesseract found any) plus a vision-LLM
  caption (if configured and the OCR pass found nothing), joined. An image with
  neither produces zero chunks — cataloged (Phase 2 behavior), not searchable — which
  is a valid outcome, not a failure.
"""
from __future__ import annotations

import logging

from app.core.config import Settings
from app.models.db import Chunk as ChunkModel
from app.models.db import get_session_factory
from app.repositories.document_repository import DocumentRepository
from app.services.chunking.chunker import Chunk, chunk_document, estimate_tokens
from app.services.embeddings.base import Embedder
from app.services.embeddings.factory import get_embedder
from app.services.extraction.loaders import (
    CorruptedFileError,
    ExtractedPage,
    ExtractionResult,
    extract,
    render_table_markdown,
)
from app.services.generation.vision_describer import describe_image
from app.services.retrieval.factory import get_vector_store
from app.services.retrieval.vector_store import VectorRecord
from app.utils.text_normalize import normalize_text

logger = logging.getLogger(__name__)


def _build_image_chunks(extraction: ExtractionResult, raw_bytes: bytes, settings: Settings) -> list[Chunk]:
    image_format = extraction.metadata.get("image_format")
    ocr_text = extraction.pages[0].text if extraction.pages else ""

    caption = None
    if extraction.is_visual_only:
        # Only attempt a caption when OCR found nothing — if OCR already produced
        # searchable text, a caption call would just cost an LLM round-trip without
        # changing whether the image is retrievable.
        caption = describe_image(raw_bytes, image_format, settings)

    combined_parts = [p for p in (caption, ocr_text) if p and p.strip()]
    if not combined_parts:
        return []

    combined_text = "\n\n".join(combined_parts)
    return [
        Chunk(
            chunk_index=0,
            text=combined_text,
            page=1,
            section=None,
            content_type="image",
            token_count=estimate_tokens(combined_text),
            extra_metadata={
                "image_width": extraction.metadata.get("image_width"),
                "image_height": extraction.metadata.get("image_height"),
                "image_format": image_format,
                "ocr_text": ocr_text or None,
                "caption": caption,
            },
        )
    ]


def _build_table_chunks(extraction: ExtractionResult, start_index: int) -> list[Chunk]:
    table_chunks = []
    for offset, table in enumerate(extraction.tables):
        text = render_table_markdown(table)
        table_chunks.append(
            Chunk(
                chunk_index=start_index + offset,
                text=text,
                page=table.page,
                section=None,
                content_type="table",
                token_count=estimate_tokens(text),
                extra_metadata={"headers": table.headers, "rows": table.rows},
            )
        )
    return table_chunks


def _build_chunks(
    extraction: ExtractionResult, file_type: str, raw_bytes: bytes, settings: Settings, embedder: Embedder
) -> list[Chunk]:
    if file_type == "image":
        return _build_image_chunks(extraction, raw_bytes, settings)

    extraction.pages = [
        ExtractedPage(page_number=p.page_number, text=normalize_text(p.text), section=p.section)
        for p in extraction.pages
    ]
    text_chunks = chunk_document(
        extraction,
        strategy=settings.chunking_strategy,
        chunk_size_tokens=settings.chunk_size_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        embedder=embedder,
        similarity_threshold=settings.semantic_chunk_similarity_threshold,
    )
    table_chunks = _build_table_chunks(extraction, start_index=len(text_chunks))
    return text_chunks + table_chunks


def run_ingestion(
    document_id: str,
    file_type: str,
    raw_bytes: bytes,
    filename: str,
    settings: Settings,
    job_id: str | None = None,
) -> None:
    session_factory = get_session_factory()
    db = session_factory()
    repo = DocumentRepository(db)
    try:
        repo.update_status(document_id, "PROCESSING")
        if job_id:
            repo.update_job(job_id, status="processing", progress=10, stage="extraction")

        extraction = extract(file_type, raw_bytes, settings)
        repo.set_page_count(document_id, extraction.page_count)
        if extraction.metadata:
            repo.update_metadata(document_id, extraction.metadata)

        # Loaded before chunking (not just before embedding) because the `semantic`
        # strategy needs an embedder to make its boundary decisions; `fixed`/`recursive`
        # ignore it. Same instance is reused for the chunk-embedding step below.
        embedder = get_embedder(settings)

        if job_id:
            repo.update_job(job_id, progress=40, stage="chunking")
        chunks = _build_chunks(extraction, file_type, raw_bytes, settings, embedder)

        if not chunks:
            if file_type == "image":
                # Cataloged (format/dimensions already stamped above) but nothing
                # extractable — OCR found no text and no vision caption is available.
                # A valid outcome, not a failure (Phase 2 behavior preserved).
                repo.replace_chunks(document_id, [])
                repo.update_status(document_id, "INDEXED")
                if job_id:
                    repo.update_job(job_id, status="completed", progress=100, stage="done")
                return
            raise CorruptedFileError("No extractable text content found in document")

        if job_id:
            repo.update_job(job_id, progress=60, stage="embedding")
        texts = [c.text for c in chunks]
        vectors = embedder.embed_documents(texts)

        db_chunks = []
        vector_records = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk_id = f"{document_id}::chunk-{chunk.chunk_index}"
            db_chunks.append(
                ChunkModel(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    content_type=chunk.content_type,
                    page=chunk.page,
                    section=chunk.section,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    embedding_model=embedder.model_name,
                    vector_id=chunk_id,
                    extra_metadata=chunk.extra_metadata,
                )
            )
            vector_records.append(
                VectorRecord(
                    vector_id=chunk_id,
                    values=vector,
                    metadata={
                        "document_id": document_id,
                        "document_name": filename,
                        "chunk_id": chunk_id,
                        "text": chunk.text,
                        "page": chunk.page,
                        "section": chunk.section,
                    },
                )
            )

        if job_id:
            repo.update_job(job_id, progress=85, stage="indexing")
        vector_store = get_vector_store(settings, embedder.dimension)
        vector_store.upsert(vector_records)

        repo.replace_chunks(document_id, db_chunks)
        if file_type != "image":
            # Images don't go through the configurable chunking pipeline (see
            # _build_image_chunks), so they're intentionally excluded from
            # chunking-strategy staleness tracking — see
            # app/services/ingestion/staleness.py and ADR 0004.
            repo.update_metadata(
                document_id,
                {
                    "indexed_with_chunking_strategy": settings.chunking_strategy,
                    "indexed_with_embedding_model": embedder.model_name,
                },
            )
        repo.update_status(document_id, "INDEXED")
        if job_id:
            repo.update_job(job_id, status="completed", progress=100, stage="done")
    except Exception as exc:
        logger.exception("Ingestion failed for document_id=%s", document_id)
        repo.update_status(document_id, "FAILED", error_message=str(exc))
        if job_id:
            repo.update_job(job_id, status="failed", error_message=str(exc))
    finally:
        db.close()
