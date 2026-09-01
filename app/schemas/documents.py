from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    file_type: str
    file_hash: str
    processing_status: str
    page_count: int | None = None
    chunk_count: int = 0
    error_message: str | None = None
    upload_timestamp: datetime
    indexed_timestamp: datetime | None = None

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class JobResponse(BaseModel):
    job_id: str
    document_id: str | None = None
    status: str
    progress: int
    stage: str | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}
