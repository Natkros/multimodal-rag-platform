# API Contracts — Phase 1 MVP

Base URL: `http://localhost:8000`. All bodies are JSON unless noted. Auth is added in
Phase 18; Phase 1 endpoints are unauthenticated for local development only.

## POST /documents/upload

`multipart/form-data`, field `file`.

**Response `202 Accepted`**
```json
{
  "document_id": "8f14e...c3a1",
  "filename": "acme_employee_handbook.md",
  "file_type": "markdown",
  "file_hash": "sha256:...",
  "status": "UPLOADED",
  "upload_timestamp": "2026-09-01T10:15:00Z"
}
```

**Errors**
- `400` unsupported file type / file too large
- `409` duplicate file (same content hash already indexed) — returns the existing document

## GET /documents

**Response `200`**
```json
{
  "documents": [
    {
      "document_id": "8f14e...c3a1",
      "filename": "acme_employee_handbook.md",
      "file_type": "markdown",
      "status": "INDEXED",
      "page_count": 1,
      "chunk_count": 12,
      "upload_timestamp": "2026-09-01T10:15:00Z"
    }
  ],
  "total": 1
}
```

## GET /documents/{document_id}

**Response `200`** — full document metadata record (see DB schema).
**Errors** — `404` if not found.

## DELETE /documents/{document_id}

Deletes the document row, its chunks, and its vectors (dense + sparse).

**Response `204`**

## POST /documents/{document_id}/reindex

Re-runs extraction → chunking → embedding for an existing document (e.g. after a
chunking-strategy change). Sets status to `REINDEX_REQUIRED` then `PROCESSING`.

**Response `202`**
```json
{ "document_id": "8f14e...c3a1", "status": "PROCESSING" }
```

## POST /query

```json
{
  "question": "What is Acme's cancellation policy?",
  "conversation_id": null,
  "top_k": 5,
  "document_ids": null
}
```

**Response `200`**
```json
{
  "answer": "Customers may cancel within 30 days of signing for a full refund [1]. After 30 days, annual-plan customers get a pro-rated refund minus a 10% early-termination fee [1].",
  "confidence": "high",
  "sources": [
    {
      "document_id": "8f14e...c3a1",
      "document_name": "acme_employee_handbook.md",
      "page": 1,
      "chunk_id": "8f14e...c3a1::chunk-7",
      "relevance_score": 0.91
    }
  ],
  "retrieval": {
    "retrieved_chunks": 5,
    "selected_chunks": 3,
    "context_tokens": 412,
    "retrieval_latency_ms": 38.2,
    "generation_latency_ms": 812.4,
    "total_latency_ms": 861.0
  }
}
```

If evidence is insufficient, `answer` is a fixed abstention string and `sources` is `[]`
(see [docs/architecture.md](architecture.md) §9 / Phase 10 grounding rules).

## GET /jobs/{job_id}

**Response `200`**
```json
{ "job_id": "...", "document_id": "...", "status": "processing", "progress": 72, "stage": "embedding", "error": null }
```

## GET /health

Liveness only — process is up. `200 {"status": "ok"}`.

## GET /ready

Readiness — checks DB and vector store connectivity. `200` or `503` with per-dependency
detail.
