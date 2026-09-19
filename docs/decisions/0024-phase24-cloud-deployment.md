# ADR 0024: Phase 24 Cloud Deployment

## What this phase can honestly deliver without cloud credentials

This project's engineering rules ("never fabricate metrics," "prove it
experimentally") apply just as much to infrastructure claims as to retrieval
numbers. This session has no cloud provider account or credentials, so it cannot
actually provision anything — meaning it cannot honestly claim a live deployment,
a real endpoint, a region, or a cost figure. What it *can* do: write real,
syntactically-valid Infrastructure-as-Code that someone with credentials could
apply, get it as close to verified as static inspection and documentation research
allow, and disclose plainly what was never run for real. That's this phase's
actual scope — `render.yaml`, not a deployed system.

## Why Render

`docs/deployment.md` already named the target since Phase 21: "a single
managed-container platform... fronting the same Docker images built in CI." Render
fits that description directly — it builds from a `Dockerfile` (no separate
buildpack/runtime translation needed for this project's Tesseract/Poppler system
dependencies, which a non-Docker PaaS would need custom buildpack work to support),
offers managed Postgres and Redis as first-class Blueprint resources, and its
`render.yaml` Blueprint format maps almost one-to-one onto
`docker-compose.yml`'s existing service list — the mental model transfers directly
instead of requiring this project's architecture to be redesigned around a
different platform's abstractions (e.g. AWS ECS task definitions + a separate RDS/
ElastiCache Terraform stack would be considerably more infrastructure to write and
verify for the same outcome, with no evidence this project needs AWS-specific
capabilities).

## Two real constraints the Blueprint had to design around — found by reasoning through the architecture, not assumed

Directly porting `docker-compose.yml`'s full topology (`api` + `worker` +
`VECTOR_STORE=pinecone`-or-`local` + `postgres` + `redis` + `frontend`) to Render
would have shipped a Blueprint that looks complete but is actually broken the
moment someone scales past the simplest case:

1. **`LocalVectorStore` needs a shared disk that Render doesn't provide between
   service instances.** `docker-compose.yml`'s `api_data` named volume is shared
   because everything runs on one Docker host; Render gives each service instance
   its own disk. Two `multimodal-rag-api` instances (Render's normal path to
   handling more traffic) would each hold a different, diverging numpy vector
   file. `render.yaml` therefore stays at Render's default (one instance) and
   documents — in the file itself, in `docs/deployment.md`, and here — that
   scaling requires `VECTOR_STORE=pinecone` first, a genuinely shared external
   store this project has already built support for since Phase 1.
2. **Phase 16's RQ job payload assumes the worker can read the file the API wrote.**
   `enqueue_ingestion()` (`app/services/ingestion/queue.py`) enqueues a file
   *path*, not the file's bytes (a deliberate Phase 16 choice — see ADR 0016 — to
   avoid round-tripping large blobs through Redis). That's correct and efficient
   when `api` and `worker` share a disk, which they do in `docker-compose.yml` and
   do **not** on Render (again, no shared disk between service instances).
   Including a `worker` service in `render.yaml` with `JOB_QUEUE_BACKEND=rq` set
   would produce jobs that enqueue successfully and then fail every single time
   the worker tries to read a file that only exists on the API's disk — a subtle,
   deploy-time-invisible failure mode, exactly the kind of thing worth catching by
   reasoning through the architecture before shipping, not after a user hits it in
   production. `render.yaml` omits the worker service entirely and keeps
   `JOB_QUEUE_BACKEND` at its default (`background_tasks`, in-process on `api`).

Both are stated as real, current limitations of this deployment target — not
solved (solving them means adding object-storage-backed uploads, out of scope for
this phase) and not silently shipped broken.

## A smaller fix this phase's own review caught: `API_BASE_URL` needs a scheme

`frontend/app.py` builds every API call as `f"{API_BASE_URL}/..."`, which requires
`API_BASE_URL` to include a scheme (`http://...`) — true in `docker-compose.yml`
(`API_BASE_URL: http://api:8000`, explicitly schemed) but not true of Render's
`fromService: property: hostport` reference, which returns a bare `host:port` with
no scheme (confirmed against Render's Blueprint documentation, not assumed).
Rather than ship a Blueprint that would produce a frontend silently failing every
request with a malformed-URL error, `frontend/app.py` now prepends `http://` when
`API_BASE_URL` has no `://` in it — a two-line fix, verified by reading Render's
own docs for what `hostport` actually returns rather than guessing.

## What was verified, and what wasn't

Verified: `render.yaml` parses as valid YAML (checked directly, `python -c "import
yaml; yaml.safe_load(...)"`); every Render-specific field used
(`fromDatabase`/`property: connectionString`, `fromService`/`property: hostport`,
`type: redis`/`property: connectionString`) was checked against Render's own
Blueprint documentation via web search this session, not invented from a vague
memory of "how PaaS YAML usually looks."

**Not verified, and stated plainly**: whether this Blueprint actually deploys
successfully on Render. No account, no credentials, no live run. The two
architectural constraints above were reasoned through from how Render's platform
model works (documented behavior: one disk per service instance, no shared disk
across services) rather than discovered by hitting them in a real failed
deployment — which is the right order (catch it before shipping) but means there
could still be a Render-specific quirk this static review didn't anticipate. If
someone applies this Blueprint against a real account, the honest next step is
reporting back what actually happened, not assuming this ADR's reasoning was
necessarily complete.

## What Phase 24 did not do

- **No real deployment, no real endpoint, no cost-per-1K-queries number** — see
  above; inventing any of these would be fabrication.
- **No autoscaling policy** — moot until the vector-store-sharing constraint is
  resolved (`VECTOR_STORE=pinecone`), since autoscaling implies more than one
  instance.
- **No Terraform/Pulumi/CloudFormation alternative** — Render's own Blueprint
  format already provides real IaC for the chosen platform; writing a second,
  parallel IaC definition for a platform this project isn't actually targeting
  would be speculative infrastructure with no deployment target, the same
  reasoning ADR 0023 used to reject a fake CI deploy job.
