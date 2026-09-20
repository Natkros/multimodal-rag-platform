# ADR 0025: Phase 25 Load Testing

## A real load test against a real server, not TestClient

`scripts/load_test.py` starts an actual `uvicorn app.main:app` subprocess (a real
ASGI server accepting real TCP connections on `127.0.0.1:8321`) against an
isolated SQLite/`LocalVectorStore` backend, seeds 5 documents, then fires
concurrent requests at it from a `ThreadPoolExecutor` using real `httpx.Client`
instances — deliberately not `TestClient` (which runs in-process and never
exercises the actual network/ASGI-server layer this phase needs to test).
`POST /query` is excluded: `get_llm_client()` raises `LLMNotConfiguredError`
(mapped to `503`) on every single call regardless of retrieval outcome, since no
`ANTHROPIC_API_KEY` is configured in this dev environment — the same constraint
noted in every LLM-dependent measurement gap since ADR 0008. Tested instead:
`GET /health`, `GET /documents`, `GET /documents/{id}/chunks`.

## The actual finding: this configuration collapses under very modest concurrency

Four real runs, in order:

| Run | Concurrency × req/worker | Total | Errors | p50 latency | Result |
|---|---|---:|---:|---:|---|
| 1 (original script, no hard deadline) | 20 × 20 | 400 | 376 (94%) | 30,007 ms | Catastrophic — wall time **17,469 seconds (~4.85 hours)**, max single-request latency **16,895 seconds** |
| 2 (after adding a hard per-run deadline) | 3 × 3 | 9 | 0 (0%) | 13 ms | Clean |
| 3 | 10 × 10 | 100 | 76 (76%) | 10,010 ms (= the timeout) | Severe degradation |
| 4 | 5 × 10 | 50 | 28 (56%) | 10,003 ms (= the timeout) | Severe degradation |

Full reports: `evaluation/reports/load_test_20260920_023331.json` (run 1),
`_030216.json` (run 2), `_030349.json` (run 3), `_030520.json` (run 4).

**This project's default local configuration — a single `uvicorn` process with no
`--workers` flag, synchronous (`def`, not `async def`) route handlers, and SQLite
as the database — has a real concurrency ceiling somewhere between 3 and 5
simultaneous clients**, past which requests start queueing behind whatever
resource is actually the bottleneck and time out rather than complete. This is
reported as a genuine, load-tested finding, not assumed from the architecture on
paper — the whole point of this phase.

## A real bug this phase's own first run caused: no hard deadline meant a ~4.85-hour hang

The original script had no upper bound on how long the load-generation phase could
run — `as_completed(futures)` waits indefinitely, and each of 20 workers running
20 *sequential* requests meant one stuck worker could (and did) block the whole
run for hours despite a 30-second per-request `timeout=30.0` that, empirically,
did not fire anywhere near 30 seconds under this failure mode (max observed
single-request latency: 16,895 seconds — over 560x the configured timeout).
Rather than accept that number as "the measurement," this was treated as a script
defect worth fixing before drawing conclusions: `wait(futures, timeout=hard_deadline_s)`
now caps the whole load-generation phase at `requests_per_worker * REQUEST_TIMEOUT_S
* 3 + 30` seconds, and any workers still running past that are abandoned (not
joined) rather than waited on indefinitely. Runs 2-4 above used this fixed script
and behaved exactly as their own configured timeouts predicted (p50/p95/p99 all
land at or near `REQUEST_TIMEOUT_S` when the server is saturated, not some
unbounded multiple of it) — confirming the fix, not just hoping it worked.

## Why, most likely — stated with appropriate hedging, not overclaimed

The most likely explanation, given what's known about this stack, is some
combination of: (1) Starlette/AnyIO runs synchronous `def` route handlers in a
bounded thread pool shared across *all* concurrent requests in the one `uvicorn`
process (no `--workers N` was configured), so once enough requests are
in-flight, new ones queue for a thread rather than executing; and (2) SQLite's
single-writer, file-level locking model degrades under concurrent access in a way
a network-based database (Postgres) doesn't. **This was not root-caused
further** — e.g., isolating whether it's specifically the thread-pool limiter,
SQLite locking, or a Windows-specific socket/event-loop interaction (this dev
sandbox is Windows; the finding has not been reproduced on Linux, where
CI/production actually run) would need instrumentation and time beyond this
phase's scope, and guessing further than the evidence supports would violate this
project's own rules. What's stated as fact is only what was directly measured:
the collapse point, the error rate, and the latency distribution at each tested
concurrency level.

## What this means for `docs/deployment.md` / `render.yaml`

Neither is changed by this phase, but the finding is directly relevant: `render.yaml`
(Phase 24) already runs one API instance against a real Postgres, not SQLite —
removing one of the two suspected bottlenecks — but still runs one `uvicorn`
process with default (not explicitly multi-worker) settings. Recommended,
**not built**, follow-up: run `uvicorn` with `--workers N` (or a process manager
like `gunicorn -k uvicorn.workers.UvicornWorker`) for any deployment expecting more
than a handful of concurrent users, and re-run this exact load test against
Postgres to see whether that alone resolves the collapse or whether the thread-pool
limiter is the dominant factor. Recorded here as the honest next step, not
implemented blind without the data to justify a specific fix.

## What Phase 25 did not do

- **No fix applied** — this phase's job was measuring and reporting, in the same
  spirit as Phase 20's "sometimes the answer is 'already correct, reported as
  such'" — except here the honest answer is "genuinely broken under load,
  reported as such," which is exactly as valid an outcome for a load-testing phase
  as a clean bill of health would have been.
- **No Postgres/multi-worker re-test** — isolating which specific factor (thread
  pool vs. SQLite vs. Windows) dominates needs a Postgres-backed run, which needs
  Docker (unavailable in this session per ADR 0021) or a real cloud deployment
  (unavailable per ADR 0024). Flagged as the natural next experiment, not run
  blind without the infrastructure to run it against.
- **No sustained/soak testing** (hours-long steady load) — the collapse already
  appears within seconds at low concurrency; a sustained-load test would currently
  just reproduce the same collapse for longer, adding runtime without new
  information until the concurrency ceiling itself is addressed.
