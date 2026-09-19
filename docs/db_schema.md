# Database Schema (PostgreSQL, via SQLAlchemy)

Phase 1 ships: `documents`, `chunks`, `jobs`. Phase 12 adds `conversations` and
`messages` without altering these. Later phases may add `citations`, `eval_runs`.

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
    text           TEXT NOT NULL,                 -- searchable/embedded form (always plain text,
                                                    -- even for table/image chunks — see extra_metadata)
    token_count    INTEGER,
    embedding_model TEXT,
    vector_id      TEXT,                          -- id in the vector store (== chunk_id today)
    extra_metadata JSONB NOT NULL DEFAULT '{}',    -- Phase 4: table headers/rows, image OCR
                                                    -- text/caption/dimensions. `text` above stays
                                                    -- the source of truth for embedding; this is
                                                    -- the structured provenance alongside it.
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

CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,              -- caller-supplied, not generated
    user_id          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    message_id                 UUID PRIMARY KEY,
    conversation_id             TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    role                         TEXT NOT NULL,     -- user | assistant
    content                      TEXT NOT NULL,
    retrieved_source_chunk_ids JSONB NOT NULL DEFAULT '[]',  -- assistant messages only
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Chunk vectors themselves live in the vector store (Pinecone or `LocalVectorStore`), not
in Postgres — Postgres holds metadata + the source-of-truth text so re-embedding
(Phase 3 chunking experiments) never re-runs extraction.
