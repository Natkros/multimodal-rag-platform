from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import db_dependency, settings_dependency
from app.core.config import Settings
from app.models.db import Document, Job
from app.repositories.document_repository import DocumentRepository
from app.schemas.documents import (
    ChunkListResponse,
    ChunkResponse,
    DocumentListResponse,
    DocumentResponse,
    JobResponse,
)
from app.services.ingestion.pipeline import run_ingestion
from app.services.ingestion.staleness import find_and_flag_stale_documents
from app.services.retrieval.factory import get_sparse_index, get_vector_store
from app.utils.hashing import classify_file_type, deterministic_document_id, sha256_bytes

router = APIRouter(tags=["documents"])


@router.post("/documents/upload", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    db: Session = Depends(db_dependency),
    settings: Settings = Depends(settings_dependency),
):
    raw_bytes = await file.read()

    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds max upload size of {settings.max_upload_size_bytes} bytes",
        )

    file_type = classify_file_type(file.filename or "")
    if file_type not in settings.allowed_file_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type!r}")

    file_hash = sha256_bytes(raw_bytes)
    repo = DocumentRepository(db)

    existing = repo.get_by_hash(file_hash)
    if existing is not None:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Duplicate document (identical content already indexed)",
                "document": DocumentResponse.model_validate(existing).model_dump(mode="json"),
            },
        )

    document = repo.create(
        Document(
            document_id=deterministic_document_id(file_hash),
            filename=file.filename or "unnamed",
            file_type=file_type,
            file_hash=file_hash,
            processing_status="UPLOADED",
        )
    )

    job = repo.create_job(Job(document_id=document.document_id, job_type="ingest", status="queued"))

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / f"{document.document_id}_{document.filename}").write_bytes(raw_bytes)

    background_tasks.add_task(
        run_ingestion,
        document.document_id,
        file_type,
        raw_bytes,
        document.filename,
        settings,
        job.job_id,
    )

    return DocumentResponse.model_validate(document).model_dump(mode="json") | {"job_id": job.job_id}


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(db: Session = Depends(db_dependency)):
    repo = DocumentRepository(db)
    docs = repo.list_all()
    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in docs], total=len(docs)
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(db_dependency)):
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    db: Session = Depends(db_dependency),
    settings: Settings = Depends(settings_dependency),
):
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        vector_store = get_vector_store(settings, embedding_dimension=384)
        vector_store.delete_by_document(document_id)
    except Exception:
        pass  # vector store cleanup best-effort; DB delete is the source of truth

    try:
        get_sparse_index(settings).delete_by_document(document_id)
    except Exception:
        pass  # sparse index cleanup best-effort; DB delete is the source of truth

    repo.delete(document_id)
    return None


@router.post("/documents/{document_id}/reindex", status_code=202)
def reindex_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(db_dependency),
    settings: Settings = Depends(settings_dependency),
):
    repo = DocumentRepository(db)
    doc = repo.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    raw_path = settings.upload_dir / f"{document_id}_{doc.filename}"
    if not raw_path.exists():
        raise HTTPException(status_code=409, detail="Original file no longer available for reindexing")

    repo.update_status(document_id, "PROCESSING")
    job = repo.create_job(Job(document_id=document_id, job_type="reindex", status="queued"))

    background_tasks.add_task(
        run_ingestion,
        document_id,
        doc.file_type,
        raw_path.read_bytes(),
        doc.filename,
        settings,
        job.job_id,
    )
    return {"document_id": document_id, "status": "PROCESSING", "job_id": job.job_id}


@router.get("/documents/{document_id}/chunks", response_model=ChunkListResponse)
def list_chunks(document_id: str, db: Session = Depends(db_dependency)):
    """Exposes chunk-level provenance — content_type and extra_metadata make table
    headers/rows and image OCR text/captions inspectable (Phase 4)."""
    repo = DocumentRepository(db)
    if repo.get(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    chunks = repo.get_chunks(document_id)
    return ChunkListResponse(chunks=[ChunkResponse.model_validate(c) for c in chunks], total=len(chunks))


@router.post("/documents/check-staleness")
def check_staleness(
    db: Session = Depends(db_dependency),
    settings: Settings = Depends(settings_dependency),
):
    """Flags indexed documents whose stored chunking strategy or embedding model no
    longer matches current config as REINDEX_REQUIRED. Does not reindex anything
    itself — see app/services/ingestion/staleness.py."""
    repo = DocumentRepository(db)
    flagged = find_and_flag_stale_documents(repo, settings)
    return {"flagged_document_ids": flagged, "count": len(flagged)}


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(db_dependency)):
    repo = DocumentRepository(db)
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)
