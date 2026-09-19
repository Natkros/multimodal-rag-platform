# API Contracts

Base URL: `http://localhost:8000`. All bodies are JSON unless noted. Auth is added in
Phase 18; all endpoints below are unauthenticated for local development only.

## POST /documents/upload

`multipart/form-data`, field `file`. Accepts PDF, TXT, Markdown, DOCX, HTML, and image
(PNG/JPEG) files — see [docs/architecture.md](architecture.md) §7 for what each type
does at ingestion time. Scanned PDFs and images are OCR'd (Tesseract) when they have
no text layer; images with no OCR-extractable text get a vision-LLM caption instead
(when an LLM is configured) or are cataloged without being searchable if neither
produces anything (see [ADR 0004](decisions/0004-phase4-multimodal-processing.md)).
PDF/DOCX tables are extracted as structured chunks (`content_type="table"`), not
flattened into surrounding text.

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
- `400` unsupported file type / file too large / empty file
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
chunking-strategy change). Sets status to `PROCESSING` immediately.

**Response `202`**
```json
{ "document_id": "8f14e...c3a1", "status": "PROCESSING" }
```

**Errors** — `404` if not found; `409` if the original uploaded file is no longer
available on disk to re-extract from.

## GET /documents/{document_id}/chunks

**Response `200`**
```json
{
  "chunks": [
    {
      "chunk_id": "8f14e...c3a1::chunk-3",
      "chunk_index": 3,
      "content_type": "table",
      "page": 2,
      "section": null,
      "text": "| Tier | Criteria | Review Frequency |\n|---|---|---|\n| Tier 1 | ... |",
      "token_count": 42,
      "extra_metadata": {
        "headers": ["Tier", "Criteria", "Review Frequency"],
        "rows": [["Tier 1", "Access to customer PII...", "Annual, on-site audit"]]
      }
    }
  ],
  "total": 12
}
```
`content_type` is `text`, `table`, or `image`. `extra_metadata` carries structured
provenance beyond the searchable `text`: table `headers`/`rows`, or an image's
`ocr_text`/`caption`/dimensions. **Errors** — `404` if the document doesn't exist.

## POST /documents/check-staleness

Scans all `INDEXED` documents and flags any whose stored `indexed_with_chunking_strategy`
/ `indexed_with_embedding_model` no longer match current server config, setting their
status to `REINDEX_REQUIRED`. Does not reindex anything itself — pair with
`POST /documents/{id}/reindex` for each flagged id. See
[docs/decisions/0002-phase2-multiformat-ingestion.md](decisions/0002-phase2-multiformat-ingestion.md).

**Response `200`**
```json
{ "flagged_document_ids": ["8f14e...c3a1"], "count": 1 }
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
      "relevance_score": 0.91,
      "content_type": "text"
    }
  ],
  "retrieval": {
    "retrieved_chunks": 5,
    "selected_chunks": 3,
    "context_tokens": 412,
    "retrieval_latency_ms": 38.2,
    "reranking_latency_ms": null,
    "generation_latency_ms": 812.4,
    "total_latency_ms": 861.0,
    "matched_content_types": [],
    "reranked": false,
    "source_distribution": { "acme_employee_handbook.md": 3 },
    "dropped_low_relevance": 0,
    "dropped_diversity_cap": 0,
    "truncated_chunks": 0
  },
  "query_intelligence": null
}
```

**Phase 9 — context engineering**: `source_distribution` (always present) shows how
many selected chunks came from each document. `dropped_low_relevance` /
`dropped_diversity_cap` / `truncated_chunks` are 0 unless
`CONTEXT_RELEVANCE_FLOOR_RATIO`, `CONTEXT_MAX_CHUNKS_PER_DOCUMENT`, or
`CONTEXT_COMPRESSION_ENABLED` are explicitly configured — see
[ADR 0009](decisions/0009-phase9-context-engineering.md).

**Phase 8 — query intelligence** (`QUERY_INTELLIGENCE_ENABLED=true`, off by default):
when enabled, `query_intelligence` is populated instead of `null`:
```json
{
  "query_intelligence": {
    "original_question": "What about Q2?",
    "effective_question": "What was Acme's Q2 2025 revenue?",
    "rewritten": true,
    "is_short": true,
    "is_ambiguous": false,
    "is_multi_part": false,
    "is_follow_up": true,
    "mentioned_years": [],
    "mentioned_quarters": [],
    "sub_questions": [],
    "expansion_variants": [],
    "matched_document_id": null,
    "retrieval_trace": [
      { "query": "What was Acme's Q2 2025 revenue?", "matched_content_types": [], "chunk_count": 5 }
    ]
  }
}
```
A follow-up question (`conversation_id` set, history exists) gets rewritten into a
self-contained form before retrieval; a multi-part/comparison question gets
decomposed into `sub_questions`, each retrieved separately and tracked in
`retrieval_trace`; a question naming a specific indexed document gets auto-scoped to
it (`matched_document_id`) unless `document_ids` was passed explicitly. Every
LLM-backed step degrades to a no-op if the LLM isn't configured — see
[ADR 0008](decisions/0008-phase8-query-intelligence.md).

If evidence is insufficient, `answer` is a fixed abstention string and `sources` is `[]`
(see [docs/architecture.md](architecture.md) §9 / Phase 10 grounding rules).

**Phase 7 — reranking**: `retrieval.reranked` reflects `RERANKER_ENABLED` at request
time (default `false`); `retrieval.reranking_latency_ms` is `null` when reranking
wasn't applied. When enabled, a wider candidate pool (`RERANK_CANDIDATE_POOL`, default
30) is retrieved and rescored by a local cross-encoder before trimming to `top_k` —
measured to *not* improve ranking quality on this project's seed dataset (see
[ADR 0007](decisions/0007-phase7-reranking.md)), which is why it defaults to off.

**Phase 5 — multimodal routing**: `retrieval.matched_content_types` shows which of
`text`/`table`/`image` the question's wording pointed retrieval at — `[]` means an
unrestricted search across all types (the "hybrid" mode). A question like "compare the
two tables" produces `["table"]` and every source's `content_type` will be `"table"`;
a question with no such signal (most questions) produces `[]` and sources can be any
type, ranked purely by relevance. See
[ADR 0005](decisions/0005-phase5-multimodal-retrieval.md).

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
