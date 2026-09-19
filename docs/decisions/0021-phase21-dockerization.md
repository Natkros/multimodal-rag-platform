# ADR 0021: Phase 21 Dockerization

## Audit first, same as Phase 15's backend refactor

Dockerization has been in place since Phase 1: `Dockerfile` (API image, with
Tesseract/Poppler system deps for Phase 4's OCR), `frontend/Dockerfile` (Streamlit
UI), and `docker-compose.yml` (`postgres`, `redis`, `api`, `frontend`, and — since
Phase 16 — `worker`). Rather than assume this phase means rebuilding any of that,
it started with a real audit: reading every Dockerfile and the compose file line by
line, checking whether the Phase 16-20 additions (the `rq` and `prometheus-client`
dependencies, the `worker` service, every new opt-in env var) actually integrate
cleanly with what's already there.

## Found: no `.dockerignore` — a real, if unglamorous, gap

`docker build`'s context is *everything in the build directory* unless
`.dockerignore` excludes it, regardless of what the `Dockerfile`'s `COPY`
instructions actually use. This project had no `.dockerignore` — every `docker
build` was sending `.venv/` (a full local virtualenv, including `sentence-transformers`'s
PyTorch dependency — large), `.git/` (full history), `data/` (local SQLite DB,
uploaded files, vector store files), and every `__pycache__/`/`.pytest_cache/` to
the Docker daemon before the build even started reading the `Dockerfile`. None of
that ever ended up *in* the image (the `Dockerfile` only `COPY`s `app` and
`workers`), but every build paid the cost of transferring it as context — slower
builds for no benefit, and a real risk that a stray `.env` (if one existed in the
build directory, which the real local dev one does) could be picked up by a less
careful `COPY app ./app`-adjacent instruction in the future. Measured, not assumed:
`du -sh .venv .git data` in this project's working tree reports `.venv` at **1.3GB**
(the `sentence-transformers`/PyTorch dependency tree) and `.git` at 2.7MB — that
1.3GB was being handed to the Docker daemon on every single `docker build` before
this phase. Added `.dockerignore` excluding `.venv/`, `.git/`, `.github/`,
`__pycache__/`/cache directories, `data/`, `evaluation/reports/`, and `.env`
explicitly.

## What was already right

- `requirements-docker.txt` (`-r requirements.txt` + `psycopg2-binary`) already
  pulls in every dependency added across Phases 16-20 (`rq`, `prometheus-client`)
  automatically — no Dockerfile change needed for those.
- The `worker` service (added in Phase 16) already builds from the same
  `Dockerfile`/context as `api`, just with a different `command:` — no duplicate
  image definition, no drift risk between the two.
- Every new opt-in setting from Phases 16-20 (`JOB_QUEUE_BACKEND`, `CACHE_ENABLED`,
  `API_KEY`, `RATE_LIMIT_ENABLED`, `LOG_JSON`, `DB_POOL_*`) defaults to its
  pre-existing (or safely inert) behavior when unset in `docker-compose.yml` — the
  compose file doesn't need to enumerate every one explicitly for `docker compose
  up` to keep working exactly as before.

## What this phase could not verify: an actual `docker build`/`docker compose up`

This session's sandboxed dev environment has the Docker CLI installed but no
working Docker daemon — `docker version` fails to connect
(`npipe:////./pipe/dockerDesktopLinuxEngine`) even after directly attempting to
start Docker Desktop and waiting several minutes for its Linux VM backend to
initialize, which it never did. This is stated plainly rather than silently
worked around: **no real `docker build` or `docker compose up` was run against
this project's current state in this session.** What *is* real verification:
`.github/workflows/ci.yml`'s `docker-build` job builds both `multimodal-rag-api`
and `multimodal-rag-frontend` images on every push to `main`, using the actual
`Dockerfile`s this ADR reviewed — that job is this project's actual, continuously-run
build check, and it will exercise the `.dockerignore` addition and every
Phase 16-20 dependency on the next CI run against this commit. This is the same
disclosure pattern as Phase 16/17's Redis-dependent integration tests: code
reviewed and unit-tested locally, real end-to-end execution deferred to the CI
environment that actually has the infrastructure this dev sandbox doesn't.

## What Phase 21 did not do

- **No multi-stage build / image size optimization** — the current single-stage
  `Dockerfile` is straightforward and this project has no measured evidence
  (image size, pull time) that it's a real problem worth the added build
  complexity of a multi-stage split. Revisit if/when Phase 24's cloud deployment
  actually measures a cost tied to image size.
- **No non-root user in the container** — a real hardening step, but one that
  needs verifying file permissions across `/app/data` (uploads, SQLite,
  vector-store files) still work correctly for a non-root UID, which this session
  couldn't verify without a working Docker daemon. Flagged here rather than
  applied blind and left unverified.
