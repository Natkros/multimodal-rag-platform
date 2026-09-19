# Deployment

## Status

**Current state: local-only (Docker Compose).** No cloud deployment exists yet — this
file will be updated with real endpoints, region, and cost data only once Phase 21/24
actually ship infrastructure. Do not read anything below as "already deployed."

## Local (Phase 1–21)

```
docker compose up
```

Services: `api` (FastAPI/uvicorn), `worker` (Redis/RQ ingestion worker — idle unless
`JOB_QUEUE_BACKEND=rq` is also set on `api`; default is Phase 1's in-process
`BackgroundTasks`, see [ADR 0016](decisions/0016-phase16-async-job-queue.md)),
`postgres`, `redis`, `frontend`. Vector store defaults to the in-process
`LocalVectorStore` unless `VECTOR_STORE=pinecone` + `PINECONE_API_KEY` are set, so
the stack runs fully offline with zero external accounts.

Verify the images build: `docker compose build`. Verify the stack comes up healthy:
`docker compose up -d && docker compose ps` (every service should reach `healthy`) —
see [ADR 0021](decisions/0021-phase21-dockerization.md) for what this project's own
CI checks on every push versus what still needs a human running `docker compose up`
locally at least once before relying on it.

## Environment Variables

See `.env.example` for the full list. Nothing here is a secret; real values live only
in a local `.env` (git-ignored) or the cloud provider's secrets manager.

## Cloud (Phase 24 — not yet implemented)

Planned target: a single managed-container platform (e.g. a PaaS with managed Postgres
and Redis add-ons) fronting the same Docker images built in CI. Will document, once
real: architecture, networking, secrets flow, autoscaling policy, and a cost estimate
per 1K queries. Pinecone remains external SaaS in every environment.
