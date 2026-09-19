# ADR 0020: Phase 20 Performance Engineering

## Measure first: profiling the ingestion pipeline before touching anything

`scripts/profile_pipeline.py` times every real ingestion stage (extraction,
embedder load, chunking, embedding, indexing) for each file in `sample_docs`,
using the actual pipeline functions — no synthetic benchmark. Full report:
`evaluation/reports/ingestion_profile_20260919_203848.json`. Totals across the
8-document corpus:

| Stage | Total (ms) | Share |
|---|---:|---:|
| embedding | 32,187 | 42% |
| embedder load (one-time, first doc only) | 21,783 | 28% |
| extraction | 7,288 | 9% |
| indexing | 891 | 1% |
| chunking | 96 | <1% |

(Percentages don't sum to 100 because embedder load is a one-time cost that
shouldn't really be amortized per-document — see below.)

**Embedding compute is the real bottleneck**, not extraction, chunking, or
indexing — unsurprising in retrospect (it's the only stage doing real numerical
work per chunk) but now measured rather than assumed. The two large plain-text
files (`pride_and_prejudice.txt`: 648 chunks, 15.9s; `sherlock_holmes.txt`: 523
chunks, 14.7s) account for nearly all of it; every other document in the corpus
(1-41 chunks) embeds in under 1.1s. This scales with chunk count, as expected —
embedding is inherently per-chunk work with no shortcut around it short of a
faster model or hardware acceleration, neither of which this phase changes (see
below).

## What was already right, confirmed rather than assumed

Two things the profiling data could have revealed as bugs, and didn't:

- **Model load is a real ~21.8s cold-start cost, but it only happens once per
  process** — `acme_employee_handbook.md` (profiled first) paid the full model
  load; every subsequent document's `embedder_load_ms` was ~0.01ms, confirming
  `get_local_embedder()`'s `@lru_cache(maxsize=4)` (Phase 1) is doing exactly its
  job. No fix needed here — this is the profiling *validating* an existing design
  decision with a real number instead of leaving it as an unverified claim in a
  docstring.
- **`embed_documents()` already batches** (`self._model.encode(texts,
  batch_size=self.batch_size, ...)`, `LocalEmbedder`) rather than embedding one
  chunk at a time — the single most common sentence-transformers performance
  mistake. Already correct since Phase 1.

Neither finding changed any code — they're reported because "we checked and it
was already right" is itself a legitimate output of a performance-engineering
pass, not a consolation prize for not finding a bug. Fabricating an optimization
to justify the phase would violate this project's core rule more than reporting
no change needed.

## What was actually changed: two real, measured wins

1. **Response compression** (`GZipMiddleware`, `app/main.py`, `minimum_size=1000`):
   `GET /documents/{id}/chunks` returns full chunk text (unlike `/query`'s
   response, which only carries `chunk_id`s/scores — see `app/schemas/query.py`),
   so a document with enough chunks produces a response well worth compressing.
   `tests/api/test_gzip_compression.py::test_large_response_is_gzip_compressed`
   confirms the server actually negotiates gzip for such a response, and
   `test_small_response_is_not_gzip_compressed` confirms the threshold is real
   (a tiny response like `/health`'s isn't compressed, avoiding framing overhead
   for no benefit).

   **A real bug this phase's own test caught, twice**: the first placement of
   `GZipMiddleware` (added after the three `BaseHTTPMiddleware`-based middlewares —
   `SecurityHeadersMiddleware`, `ObservabilityMiddleware`, `RateLimitMiddleware` —
   in the `add_middleware()` call sequence) compressed *every* response regardless
   of size. Starlette's `Starlette.build_middleware_stack()` builds the stack in
   *reverse* call order — the middleware added **first** ends up **innermost**
   (closest to the router), and the one added **last** ends up **outermost**
   (closest to the client) — the opposite of what a naive reading of "add this
   middleware after that one" suggests. Getting that backwards the first time
   (moving `GZipMiddleware` to be added *last*, intending it to sit closest to the
   routes) actually made it the *outermost* layer, wrapping the three
   `BaseHTTPMiddleware`-based middlewares that convert responses into a streaming
   shell with no known `Content-Length` — which `GZipMiddleware` can't evaluate
   `minimum_size` against, so it compressed unconditionally, same symptom as
   before. The fix was to add `GZipMiddleware` **first**, so it's truly innermost
   and sees the route's original response — with a real `Content-Length` — before
   anything else touches it.
   `test_small_response_is_not_gzip_compressed` caught both wrong orderings by
   actually failing, not by inspection or by trusting a plausible-sounding
   explanation the first time.

2. **Database connection pool tuning** (`app/models/db.py::get_engine()`,
   `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_PRE_PING`, default 5/10/true):
   applies only to non-SQLite engines — a SQLite connection is a local file
   handle, not a network resource, so pool tuning is meaningless for it (the
   `sqlite:///` branch is unchanged). `pool_pre_ping=True` sends a lightweight
   `SELECT 1` before handing out a pooled connection, transparently replacing one
   the database server silently dropped (idle timeout, restart) instead of
   surfacing a confusing mid-request error — the single highest-value, lowest-risk
   pool setting for a service expected to stay up across a Postgres restart.
   `tests/unit/test_db_engine.py` verifies the SQLite path stays exactly as before
   and the Postgres path receives the configured pool kwargs.

## What Phase 20 did not do

- **No embedding model swap or GPU acceleration** — the profiling data shows
  embedding as the bottleneck, but addressing that means either a faster/smaller
  model (a quality tradeoff requiring its own measured comparison, in the spirit
  of Phase 3's chunking comparison) or hardware this project has no evidence of
  having access to in its target deployment. Neither is something this phase can
  respons`ibly claim without a real before/after number on real hardware.
- **No caching of ingestion itself** — Phase 17 already covers retrieval caching;
  ingestion is a one-time-per-document operation (Phase 1's `file_hash`-based
  idempotent re-upload already prevents redundant re-ingestion of identical
  files), so there's no repeated cost here to cache.
- **No load/throughput testing** — that's explicitly Phase 25's scope; this phase
  is about where time goes in one request/ingestion, not sustained concurrent
  traffic.
