# Deployment

## Status

**Current state: local (Docker Compose) plus an unverified cloud Blueprint
(`render.yaml`, Phase 24).** No live cloud deployment exists — `render.yaml` was
never applied against a real Render account in the session that wrote it (no cloud
credentials available), so nothing below the "Cloud" section is a claim that
anything is actually running anywhere. This file will gain real endpoints, region,
and cost data only once someone with Render access actually runs the Blueprint and
reports back what happened.

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

## Cloud (Phase 24 — Blueprint written, never deployed)

`render.yaml` is a [Render Blueprint](https://render.com/docs/infrastructure-as-code)
defining `multimodal-rag-api` (Docker web service, the same `Dockerfile` CI already
builds), `multimodal-rag-frontend` (the Streamlit UI), a managed Postgres database,
and a managed Redis/Key-Value instance. Deploy: connect this repo in the Render
dashboard ("New +" → "Blueprint"), point it at `render.yaml`, fill in the
`sync: false` secrets (`ANTHROPIC_API_KEY`, and `PINECONE_API_KEY`/`API_KEY` if
used) in the dashboard.

**Deliberately narrower than `docker-compose.yml`**: no `worker` service, and
`VECTOR_STORE` stays `local`, not `pinecone`. Both are real architectural
constraints, not oversights — see
[ADR 0024](decisions/0024-phase24-cloud-deployment.md):
- `LocalVectorStore` is a numpy file on one service's own disk. Render doesn't give
  two service instances a shared disk the way `docker-compose.yml`'s `api_data`
  volume does. Scaling `multimodal-rag-api` past one instance, or adding a separate
  worker service, needs `VECTOR_STORE=pinecone` (a real shared external store)
  first — silently shipping a config that breaks at 2 instances would be worse than
  the single-instance limit stated plainly here.
- Phase 16's RQ job payload is a file *path*, assuming the worker can read the same
  disk the API wrote the upload to. That assumption holds in `docker-compose.yml`
  (shared volume) and breaks on Render (no shared disk between services) — so the
  Blueprint keeps `JOB_QUEUE_BACKEND` at its default (`background_tasks`,
  in-process on the API) rather than including a worker service that would enqueue
  jobs it could never actually process.

**Not done, and not claimed**: no live deployment exists (no cloud credentials were
available to actually run this Blueprint), so there's no real endpoint, region, or
cost-per-1K-queries number to report — a number invented here would be exactly the
kind of fabricated metric this project's engineering rules forbid. Autoscaling
policy is also unconfigured (`render.yaml` fixes one instance per service, per the
scaling constraint above).
