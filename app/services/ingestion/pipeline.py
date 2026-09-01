"""Ingestion pipeline: extraction -> chunking -> embedding -> indexing.

Runs synchronously inside a FastAPI BackgroundTask in Phase 1 (see
docs/decisions/0001-phase1-stack-choices.md for why, and the Phase 16 upgrade path).
"""
from __future__ import annotations

import logging

from app.core.config import Settings
from app.models.db import Chunk as ChunkModel
from app.models.db import get_session_factory
from app.repositories.document_repository import DocumentRepository
from app.services.chunking.chunker import chunk_document
from app.services.embeddings.factory import get_embedder
from app.services.extraction.loaders import CorruptedFileError, extract
from app.services.retrieval.factory import get_vector_store
from app.services.retrieval.vector_store import VectorRecord

logger = logging.getLogger(__name__)


def run_ingestion(document_id: str, file_type: str, raw_bytes: bytes, filename: str, settings: Settings, job_id: str | None = None) -> None:
    session_factory = get_session_factory()
    db = session_factory()
    repo = DocumentRepository(db)
    try:
        repo.update_status(document_id, "PROCESSING")
        if job_id:
            repo.update_job(job_id, status="processing", progress=10, stage="extraction")

        extraction = extract(file_type, raw_bytes)
        repo.set_page_count(document_id, extraction.page_count)

        if job_id:
            repo.update_job(job_id, progress=40, stage="chunking")
        chunks = chunk_document(
            extraction,
            strategy=settings.chunking_strategy,
            chunk_size_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
        if not chunks:
            raise CorruptedFileError("No extractable text content found in document")

        if job_id:
            repo.update_job(job_id, progress=60, stage="embedding")
        embedder = get_embedder(settings)
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
