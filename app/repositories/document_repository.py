from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import Chunk, Document, Job


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_hash(self, file_hash: str) -> Document | None:
        return self.db.execute(select(Document).where(Document.file_hash == file_hash)).scalar_one_or_none()

    def get(self, document_id: str) -> Document | None:
        return self.db.get(Document, document_id)

    def list_all(self) -> list[Document]:
        return list(self.db.execute(select(Document).order_by(Document.upload_timestamp.desc())).scalars())

    def create(self, document: Document) -> Document:
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def update_status(
        self, document_id: str, status: str, error_message: str | None = None
    ) -> None:
        doc = self.get(document_id)
        if doc is None:
            return
        doc.processing_status = status
        doc.error_message = error_message
        if status == "INDEXED":
            doc.indexed_timestamp = datetime.now(UTC)
        self.db.commit()

    def set_page_count(self, document_id: str, page_count: int) -> None:
        doc = self.get(document_id)
        if doc is None:
            return
        doc.page_count = page_count
        self.db.commit()

    def replace_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        self.db.query(Chunk).filter(Chunk.document_id == document_id).delete()
        for chunk in chunks:
            self.db.add(chunk)
        doc = self.get(document_id)
        if doc is not None:
            doc.chunk_count = len(chunks)
        self.db.commit()

    def delete(self, document_id: str) -> None:
        doc = self.get(document_id)
        if doc is not None:
            self.db.delete(doc)
            self.db.commit()

    def get_chunks(self, document_id: str) -> list[Chunk]:
        return list(
            self.db.execute(
                select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
            ).scalars()
        )

    # --- Jobs ---
    def create_job(self, job: Job) -> Job:
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self.db.get(Job, job_id)

    def update_job(
        self,
        job_id: str,
        status: str | None = None,
        progress: int | None = None,
        stage: str | None = None,
        error_message: str | None = None,
    ) -> None:
        job = self.get_job(job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if stage is not None:
            job.stage = stage
        if error_message is not None:
            job.error_message = error_message
        if status == "completed" or status == "failed":
            job.completed_at = datetime.now(UTC)
        self.db.commit()
