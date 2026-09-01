# ADR 0001: Phase 1 Stack Choices

## Embedding model
Default `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-friendly, no API key).
Configurable via `EMBEDDING_MODEL` / `EMBEDDING_PROVIDER` so a hosted model (e.g. an
Anthropic/OpenAI/Voyage embedding endpoint) can be swapped in without code changes —
only `app/services/embeddings/factory.py` branches on provider.

## Vector store
Pinecone is the named production target in the brief, but requiring a live Pinecone
account to run `pytest` would break CI and onboarding. `VectorStore` is a Protocol
(`app/services/retrieval/vector_store.py`); `PineconeVectorStore` and `LocalVectorStore`
(numpy cosine-sim, disk-persisted) both implement it. `VECTOR_STORE=local` is the
default; set `VECTOR_STORE=pinecone` + `PINECONE_API_KEY`/`PINECONE_INDEX` to switch.
This is what NFR-2 in `docs/architecture.md` requires, not a deviation from it.

## LLM
`anthropic` SDK, model configurable via `LLM_MODEL` (default `claude-sonnet-5`). No key
in this repo or in CI secrets by default; `app/services/generation/llm_client.py` raises
a clear `LLMNotConfiguredError` (caught by the API layer as a 503) rather than crashing,
and every generation-path test mocks the client — no test requires a live API key.

## Database
PostgreSQL in Docker Compose / production, `DATABASE_URL` driven. Tests and default
local dev use SQLite (`sqlite:///./dev.db`) via the same SQLAlchemy models — no
Postgres-only SQL (JSONB is handled through SQLAlchemy's `JSON` type, which degrades
to SQLite's JSON1 automatically) so the schema in `docs/db_schema.md` stays accurate for
both.

## Async ingestion (Phase 16 pulled forward partially)
Phase 1 uses FastAPI `BackgroundTasks` for the upload → process pipeline rather than a
real Redis/RQ queue, to keep the MVP runnable with one process. The `IngestionJob`
interface is written so swapping the executor for an RQ/Celery worker (Phase 16) only
touches `app/services/ingestion/job_runner.py`, not the pipeline steps.
