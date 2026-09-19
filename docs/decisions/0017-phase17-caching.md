# ADR 0017: Phase 17 Caching

## What gets cached: retrieval, not generation

`app/core/config.py` already had `cache_enabled`/`cache_ttl_seconds` scaffolded
since Phase 1. This phase decides *what* they gate: retrieval results
(`retrieve_with_classification()`'s output — the embedding call, vector search,
optional BM25 fusion, and content-type routing), not LLM generation. Two reasons:

1. **It's measurable in this dev environment.** No `ANTHROPIC_API_KEY` is
   configured here (the same constraint noted in ADR 0008 and ADR 0013), so caching
   generation and reporting a "before/after" latency number would mean fabricating
   or guessing what a real LLM call costs — against this project's core rule.
   Retrieval runs entirely on local models (`sentence-transformers` embeddings,
   numpy vector search, optional local BM25/cross-encoder), so a cache hit's
   speedup is something this session can actually run and report honestly.
2. **It's the right layer regardless.** A full-response cache (including the
   generated answer) would need to key on the *effective* question after Phase 8's
   rewriting/decomposition — correct, but a bigger surface with more staleness edge
   cases (an answer's citations reference specific chunk_ids that could change on
   reindex). Caching one level down, at retrieval, is simpler, still captures most
   of the latency (retrieval + reranking, not just generation, per the Phase 6/7
   latency numbers in `docs/evaluation.md`), and composes cleanly: if a future phase
   adds generation caching, it layers on top of this without needing to change it.

## Implementation: a decorator, not a new retriever

`CachingRetriever` (`app/services/retrieval/retriever.py`) wraps any object
implementing the existing `Retriever` protocol (`DenseRetriever` or
`HybridRetriever`) and exposes the identical `retrieve()`/`retrieve_with_classification()`
shape — the same pattern this project already uses for `LocalVectorStore` vs.
`PineconeVectorStore` behind one `VectorStore` interface, and consistent with every
other opt-in Phase-N capability (hybrid retrieval, reranking, query intelligence):
`app/services/retrieval/factory.py::get_retriever()` wraps the chosen retriever in
`CachingRetriever` only when `CACHE_ENABLED=true`, so nothing downstream (the query
service, the eval scripts) needs to know caching is involved, and the default
(`CACHE_ENABLED=false`) is byte-for-byte the pre-Phase-17 behavior.

Cache key: SHA-256 of `{query, top_k, document_ids (sorted), retrieval_mode,
embedding_model}` as canonical JSON — everything that actually changes what
`retrieve_with_classification()` returns for the same underlying index. Value:
the `RetrievalResult` (chunks + matched content types) as JSON, round-tripped back
into the same dataclasses on a hit.

## Staleness: bounded by TTL, not eliminated — disclosed, not solved

A cached retrieval result can be stale for up to `CACHE_TTL_SECONDS` (default
3600s) after a document is ingested, reindexed, or deleted — the cache has no
invalidation hook into `DocumentRepository`/`run_ingestion`. A correct fix exists
(a Redis-stored monotonic "index version" counter, bumped on every mutation and
folded into the cache key) but was deliberately not built this phase: it adds a new
coupling (every document-mutating code path now has to remember to bump a version)
for a staleness window that, at this project's scale and with a 1-hour default TTL,
is a reasonable tradeoff most systems make deliberately — not a correctness bug
being quietly ignored. Anyone deploying this with `CACHE_ENABLED=true` and frequent
document churn should lower `CACHE_TTL_SECONDS` accordingly; this tradeoff is
stated here and in README rather than hidden.

## Measured: cache hit vs. cache miss, real Redis, real embedder

`tests/integration/test_retrieval_caching.py` ingests a real document, retrieves
the same query twice through a real `CachingRetriever` backed by a real Redis, and
asserts (not just claims) that the second call is faster and returns byte-identical
chunk ids and text — proving both the *correctness* (a cache hit doesn't silently
diverge from a miss) and the *performance claim* in the same test, rather than
splitting them into an assumption plus a separate benchmark script. Like Phase 16's
`test_job_queue_rq.py`, this test is **skipped in this local dev session** (no
Redis reachable at `redis://localhost:6379/0`, confirmed by directly attempting a
connection) but runs for real in CI, which already gained a `redis:7-alpine`
service container in Phase 16 — no further CI changes needed this phase. No
specific millisecond figure is claimed in README/docs, since the actual number
depends on the machine running the test; the test asserts the *relationship*
(faster, identical results) that will hold wherever it runs, which is what's
verifiable without a specific run's numbers in hand.

## What Phase 17 did not cache

- **Generation/LLM responses** — see above; deferred pending a configured LLM to
  measure against honestly, same reasoning as Phase 8/13's query-intelligence
  measurement gaps.
- **Embeddings themselves** (as opposed to retrieval results) — caching
  `embed_query()` alone would save re-embedding an identical query string, but
  retrieval-result caching already subsumes that benefit (a cache hit skips
  embedding *and* the vector/BM25 search), so a separate embedding-only cache
  layer would add complexity without adding coverage.
- **Document-level content caches** (e.g. caching extracted text so re-ingesting an
  unchanged file skips extraction) — `Document.file_hash`-based idempotent
  re-upload (Phase 1, `409` on duplicate) already prevents redundant ingestion of
  identical files; there's no repeated-extraction cost left to cache.
