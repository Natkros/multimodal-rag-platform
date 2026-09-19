# ADR 0015: Phase 15 Backend Service-Layer Architecture

## Audit first, refactor only where inspection actually found a violation

The brief's Phase 15 goal is a clean backend service-layer separation. Rather than
assume this needs new structure, this phase started by inspecting what already
exists: `app/api/routes/*.py` (HTTP layer — request parsing, status codes),
`app/services/*/` (domain logic, organized by capability: chunking, embeddings,
extraction, generation, ingestion, query_intelligence, reranking, retrieval,
evaluation), `app/repositories/*.py` (persistence, one per aggregate:
`DocumentRepository`, `ConversationRepository`), and `app/models/db.py` (ORM). This
layering has existed since Phase 1 — every prior phase added its logic to
`app/services/<capability>/`, not to the routes. `app/middleware/` and
`app/services/observability/` are pre-scaffolded empty packages, intentionally
unpopulated until Phase 18 (auth/rate-limiting) and Phase 19 (structured
logging/metrics) actually need them — leaving them empty now is the correct call,
not an oversight; populating them prematurely with no consumer would be exactly the
kind of speculative abstraction this project's rules warn against.

One genuine violation was found: `app/api/routes/query.py`'s `POST /query` handler
was ~180 lines of real orchestration logic — conversation history lookup, query
intelligence invocation, multi-query retrieval with merge-by-best-score, reranking,
generation, and conversation persistence — living directly in the HTTP route
function, not in a service. Every other route (`documents.py`, `health.py`) is
already thin (parse request, delegate to a repository or a Phase-N pipeline function,
map to a response schema); `query.py` was the one outlier, because Phase 8-12 each
added their piece of orchestration directly into the growing route function rather
than extracting it, and no phase's brief called "extract this" out as its own task
until now.

## The fix: `app/services/query_service.py`, pure code motion

`run_query_pipeline(request, db, settings) -> QueryPipelineResult` now holds exactly
the orchestration logic that was in the route, unchanged line-for-line except for the
return shape (a `QueryPipelineResult` dataclass bundling the generation result, query
intelligence result, retrieval trace, and latency figures the route needs to build
its response). `app/api/routes/query.py` is now ~110 lines, all of it either FastAPI
wiring or `QueryResponse` field mapping — no retrieval/generation logic. This is
**pure code motion, not a rewrite**: the exact same functions get called in the exact
same order with the exact same arguments; only which module contains the code
changed. Verified with the full pre-existing test suite (`tests/api/test_query.py`,
`tests/adversarial/test_adversarial.py`) rather than re-derived from scratch — the
whole point of a refactor is that behavior doesn't change, so the existing tests
(updated only to patch `app.services.query_service.get_llm_client` instead of
`app.api.routes.query.get_llm_client`, since that's where the call now lives) are the
proof, not new tests written to match new behavior.

## Why this, and not a class-based service or a bigger restructure

A single function (`run_query_pipeline`) rather than a `QueryService` class:
there's no state to hold between calls and no need for polymorphism (unlike
`VectorStore`/`LLMClient`, which genuinely have multiple implementations behind a
`Protocol`) — a class here would be structure without a reason, the same trap this
project avoided in Phase 1 by choosing functions over classes wherever there's only
one real implementation. `document.py`'s route handlers were also audited and left
alone: `upload_document` is already thin (validate → `DocumentRepository.create` →
write file → queue `run_ingestion` background task), with the actual multi-format
ingestion logic already living in `app/services/ingestion/pipeline.py` since Phase 1.
There was nothing to extract there.

## What Phase 15 did not do

No new abstraction layers (no generic `BaseService`, no dependency-injection
container beyond FastAPI's own `Depends`), no interface/Protocol added for
`query_service` (unlike `VectorStore`, it has exactly one implementation and no
reason to expect a second), and no change to `app/repositories/*` or
`app/models/db.py` — both were already correctly scoped. Phase 15's actual, honest
scope was one file's worth of extraction, found by looking rather than assumed
necessary going in.
