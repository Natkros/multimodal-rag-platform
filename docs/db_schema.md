# Database Schema (PostgreSQL, via SQLAlchemy)

Phase 1 ships: `documents`, `chunks`, `jobs`. Later phases add `conversations`,
`messages`, `citations`, `eval_runs` without altering these.

```sql
CREATE TABLE documents (
    document_id      UUID PRIMARY KEY,
    filename          TEXT NOT NULL,
    file_type         TEXT NOT NULL,           -- pdf | docx | txt | markdown | html | image
    file_hash         TEXT NOT NULL UNIQUE,     -- sha256, drives idempotent re-upload
    source             TEXT,                    -- e.g. "upload", "url"
    page_count        INTEGER,
    processing_status TEXT NOT NULL,            -- UPLOADED | PROCESSING | INDEXED | FAILED | REINDEX_REQUIRED
    error_message     TEXT,
    metadata_json     JSONB NOT NULL DEFAULT '{}',
    upload_timestamp  TIMESTAMPTZ NOT NULL DEFAULT now(),
    indexed_timestamp TIMESTAMPTZ
);

CREATE TABLE chunks (
    chunk_id       TEXT PRIMARY KEY,             -- "{document_id}::chunk-{index}"
    document_id    UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index    INTEGER NOT NULL,
    content_type   TEXT NOT NULL DEFAULT 'text',  -- text | table | image
    page           INTEGER,
    section        TEXT,
    text           TEXT NOT NULL,
    token_count    INTEGER,
    embedding_model TEXT,
    vector_id      TEXT,                          -- id in the vector store (== chunk_id today)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_document_id ON chunks(document_id);

CREATE TABLE jobs (
    job_id        UUID PRIMARY KEY,
    document_id   UUID REFERENCES documents(document_id) ON DELETE CASCADE,
    job_type      TEXT NOT NULL,                  -- ingest | reindex
    status        TEXT NOT NULL,                  -- queued | processing | completed | failed
    progress      INTEGER NOT NULL DEFAULT 0,
    stage         TEXT,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);
```

Chunk vectors themselves live in the vector store (Pinecone or `LocalVectorStore`), not
in Postgres — Postgres holds metadata + the source-of-truth text so re-embedding
(Phase 3 chunking experiments) never re-runs extraction.
