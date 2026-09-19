# ADR 0019: Phase 19 Observability

## Two capabilities, both building on scaffolding already in place

`LOG_JSON` (`app/core/config.py`) has existed since Phase 1 but was never read —
`logging.basicConfig()` ignored it. This phase makes it real:
`app/services/observability/logging_config.py::configure_logging()` switches
between a plain-text formatter (default, readable in a local terminal — unchanged
from before) and `JsonFormatter` (one JSON object per line: timestamp, level,
logger, message, plus whatever a caller passes via `extra={...}`) when
`LOG_JSON=true`. No new logging framework (no `structlog`) — stdlib `logging` with
a custom `Formatter` does the whole job in under 40 lines, and this project already
uses stdlib `logging` everywhere else.

The second capability, Prometheus metrics via `GET /metrics`, is new: a
`prometheus-client` dependency (the standard, minimal choice — not a custom metrics
format) backing four series: `http_requests_total` (method/path/status_code),
`http_request_duration_seconds` (method/path), `retrieval_cache_total`
(hit/miss, wired into Phase 17's `CachingRetriever`), and
`rate_limit_rejections_total` (wired into Phase 18's `RateLimitMiddleware`). The
latter two aren't new instrumentation bolted on after the fact — they're this
phase connecting existing Phase 17/18 decision points (a cache hit vs. miss, a
request allowed vs. rate-limited) to a metric, since those are exactly the numbers
an operator would want from those features and building the features without ever
exposing them would leave the "was Phase 17's cache actually being hit in
production" question unanswerable except by reading logs.

## Always-on, like Phase 18's security headers — for the same reason

`ObservabilityMiddleware` (`app/middleware/observability.py`) logs one line per
request and updates both HTTP metrics on every request, with no `OBSERVABILITY_ENABLED`
flag. Same reasoning as Phase 18's `SecurityHeadersMiddleware`: there's no
legitimate-client-facing cost to weigh (a client's response is identical whether or
not this middleware runs), so gating it behind a flag would only add a footgun
(someone forgets to enable it and has no logs when something breaks) for no
benefit.

## Metric labels use the route template, not the literal URL

`_route_path()` reads `request.scope["route"].path` — the matched route's path
*pattern* (`/documents/{document_id}`), not the resolved URL
(`/documents/a1b2c3...`). Using the literal path as a Prometheus label would create
a new time series per distinct `document_id` ever requested — unbounded
cardinality, a well-documented Prometheus anti-pattern that degrades query
performance and storage as the label set grows without bound. Falls back to the
literal path only for unmatched routes (404s with no route to template from).
`tests/api/test_observability.py::test_request_counter_uses_route_template_not_literal_path`
verifies two different document IDs increment the *same* label combination rather
than creating two.

## `/metrics` is unauthenticated, exempt from rate limiting — same as `/health`/`/ready`

Living under `health.router` in `app/main.py` (included without the
`Depends(require_api_key)` the other routers get) means `/metrics` never requires
`X-API-Key`, and it's explicitly added to `RateLimitMiddleware`'s exempt-path set.
A Prometheus scraper hitting this endpoint every 15-30 seconds shouldn't need
service credentials or risk tripping a rate limit meant for abuse on the actual
API surface — the same operational-infrastructure reasoning that already exempted
`/health` and `/ready` in Phase 18.

## What Phase 19 did not build

- **Distributed tracing** (OpenTelemetry spans across retrieval/generation stages)
  — genuinely valuable for a multi-service deployment, but this project is a
  single API process plus an optional worker (Phase 16); the existing per-stage
  latency breakdown already in `QueryResponse.retrieval` (`retrieval_latency_ms`,
  `reranking_latency_ms`, `generation_latency_ms`, `total_latency_ms`, shipped
  since Phase 1/7/10) already answers "where did the time go" for the one request
  path that matters, without needing a tracing backend to view it.
- **A pre-built Grafana dashboard** — `/metrics` exposes what a dashboard would
  need, but building and shipping dashboard JSON with no real traffic history to
  validate panel thresholds against would be guessing at what matters, not
  measuring it (Phase 28's admin dashboard is a more honest place for this, once
  there's a evaluation/usage history to actually visualize).
- **Log aggregation/shipping** (e.g. a Fluentd/Vector sidecar in
  `docker-compose.yml`) — `LOG_JSON=true` makes this project's logs consumable by
  any standard log shipper; wiring up a specific one with no target log backend
  (no ELK/Loki/Datadog configured for this project) would be infrastructure with
  nowhere to point.
