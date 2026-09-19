# ADR 0016: Phase 16 Asynchronous Job Queue

## Opt-in, not a replacement — same pattern as every phase since Phase 6

The brief's Phase 16 goal is replacing FastAPI's in-process `BackgroundTasks` with a
real job queue. Fully replacing it would mean every deployment — including local
dev, CI, and anyone cloning this repo to try it — now needs a running Redis and a
separate worker process just to upload a document, for a capability (surviving an
API restart, scaling ingestion across worker processes) that only matters once you
actually run multiple API replicas or care about jobs outliving a restart. Neither
is true for local dev. So this phase follows the same pattern as hybrid retrieval
(Phase 6), reranking (Phase 7), and query intelligence (Phase 8): a new capability,
off by default, that doesn't change any existing behavior until explicitly turned
on. `JOB_QUEUE_BACKEND=background_tasks` (default) is byte-for-byte Phase 1's
original behavior; `JOB_QUEUE_BACKEND=rq` switches both `/documents/upload` and
`/documents/{id}/reindex` to enqueue onto Redis instead.

## Why RQ, not Celery

`docker-compose.yml` already had `redis` provisioned and a `# NOTE: a dedicated
worker service (Redis/RQ-backed) ships in Phase 16` comment — RQ was already the
intended choice going into this phase, for reasons that check out on inspection:
this project has exactly one job type (document ingestion), no need for complex
task routing, scheduled/periodic tasks, or multi-broker support, all of which
Celery adds real operational weight for. RQ is a thin, synchronous-feeling layer
directly on Redis (a dependency this project already has for Phase 17's cache) —
`Queue.enqueue(fn, *args)` and a `Worker([queue]).work()` loop, both understandable
in a few minutes. Choosing Celery here would be adopting the more complex tool for
capabilities this project doesn't need, the same category of mistake as premature
abstraction.

## What actually changed

- `app/core/config.py`: `job_queue_backend` (`"background_tasks"` | `"rq"`),
  `job_queue_name`, `job_queue_timeout_seconds`.
- `app/services/ingestion/queue.py`: `get_queue()` (raises
  `JobQueueNotConfiguredError` if `REDIS_URL` isn't set, mirroring
  `LLMNotConfiguredError`'s "fail loud" pattern), `enqueue_ingestion()`, and
  `run_ingestion_from_disk()` — the actual function a worker calls.
- `app/api/routes/documents.py`: a small `_schedule_ingestion()` helper picks
  `BackgroundTasks.add_task` or `enqueue_ingestion` based on
  `settings.job_queue_backend`; both call sites (`upload_document`,
  `reindex_document`) route through it instead of hardcoding `BackgroundTasks`.
- `workers/ingestion_worker.py`: the worker entrypoint (`python
  workers/ingestion_worker.py`) — this directory and the Dockerfile's `COPY workers
  ./workers` already existed, pre-scaffolded for this phase.
- `docker-compose.yml`: a `worker` service, same image as `api`, running the worker
  script instead of `uvicorn`. Only does something when `JOB_QUEUE_BACKEND=rq` is
  also set on the `api` service — the compose file's default is still
  `background_tasks` everywhere, so `docker compose up` behavior is unchanged unless
  someone opts in.

## Redis job payload: a file path, not the raw bytes

`run_ingestion()`'s existing signature takes `raw_bytes: bytes` directly, and the
`background_tasks` backend still passes it that way (no serialization cost — it's
an in-process call). For the `rq` backend, pushing a file's full bytes through Redis
as a pickled job argument would be wasteful — files can be up to
`MAX_UPLOAD_SIZE_BYTES` (25MB default) — and Redis isn't meant as blob storage.
Since `app/api/routes/documents.py` already writes the upload to `upload_dir` before
scheduling ingestion (needed for `reindex` regardless), `enqueue_ingestion()` instead
enqueues `run_ingestion_from_disk(document_id, file_type, upload_path, filename,
settings, job_id)`, which reads the file back from disk in the worker process and
then calls the real `run_ingestion()`. This only works when the API and worker share
the upload directory — true in `docker-compose.yml` (`api_data` volume mounted on
both), and stated as a requirement, not assumed silently.

## Testing: unit-level with mocks, end-to-end with a real Redis in CI — honestly, not locally

`tests/unit/test_ingestion_queue.py` mocks the RQ `Queue`/Redis connection to verify
the routing logic (`get_queue` fails correctly without `REDIS_URL`, `enqueue_ingestion`
enqueues the right function with the right arguments, `run_ingestion_from_disk`
reads the file and delegates correctly) without needing a real Redis.
`tests/api/test_documents.py::test_upload_with_rq_backend_enqueues_instead_of_running_in_process`
similarly mocks `enqueue_ingestion` to prove the route picks the right backend.

For genuine end-to-end proof — enqueue a real job onto a real Redis, run a real RQ
`Worker` against it, confirm the document actually gets indexed —
`tests/integration/test_job_queue_rq.py` does exactly that, with **no mocking of
Redis or RQ**. This test is skipped when no Redis is reachable at
`redis://localhost:6379/0`, which is the case in this project's local dev sandbox
(no Docker daemon running, no local Redis installed at the time this phase was
built — confirmed by directly attempting a connection, not assumed). It is **not**
skipped in CI: `.github/workflows/ci.yml` now runs a real `redis:7-alpine` service
container specifically so this test executes for real there, which means the actual
verification that this phase's queue integration works end-to-end happens on the
next CI run against this commit, not in this development session. Stated plainly
rather than silently gapped: this phase's RQ path is verified by code review, unit
tests with mocks, and a real integration test that will run in CI — not by a local
end-to-end run, because no Redis was reachable to run one against.

## What Phase 16 did not do

- No retry/backoff policy beyond RQ's defaults, no dead-letter queue, no job
  priority tiers — none of these have a concrete need yet at this project's single
  job-type scale; adding them now would be speculative.
- The `Job` model's `status`/`progress`/`stage` fields (Phase 1) are unchanged and
  still the source of truth `GET /jobs/{job_id}` reads from — RQ's own job
  tracking is not exposed via the API, avoiding two parallel "job status" concepts.
- No horizontal worker scaling demo (multiple `worker` replicas) — `docker-compose.yml`
  runs one, since demonstrating N replicas doesn't need N replicas actually running
  to prove the architecture supports it (RQ workers are stateless and safely run in
  parallel by design).
