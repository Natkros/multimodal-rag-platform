# ADR 0018: Phase 18 Security Hardening

## Three concerns, three different defaults

The brief's Phase 18 goal bundles API-key/JWT auth, rate limiting, and input
sanitization. These aren't one feature — they have genuinely different risk/cost
tradeoffs, so they get different defaults rather than one blanket "security mode"
flag:

- **API key auth**: activates the moment `API_KEY` is set — no separate
  `AUTH_ENABLED` flag to also remember to flip, since an operator who sets a key
  clearly wants it enforced. `app/api/deps.py::require_api_key` is a no-op when
  `API_KEY` is unset (this project's default — README's Security section has
  always said "local-dev only, no auth"). Applied per-router in `app/main.py`
  (`documents.router`, `query.router`), not globally: `/health` and `/ready` stay
  key-free, since Kubernetes-style liveness/readiness probes hit those before any
  key is provisioned to them, and gating them would make orchestration harder for
  no security benefit (those endpoints reveal nothing sensitive).
- **Rate limiting**: `RATE_LIMIT_ENABLED=true`, off by default — unlike auth, this
  has a real behavioral cost even for legitimate traffic (a burst of valid requests
  can get throttled), so it stays opt-in rather than activating implicitly.
- **Response security headers** (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`): always on, no flag at all. These headers only constrain how
  *browsers* treat responses (MIME sniffing, framing, referrer leakage) — an API
  client (or `curl`, or the test suite) is completely unaffected, so there's no
  legitimate-client-facing cost to weigh, unlike the other two. No
  `Content-Security-Policy` is set: this is a JSON API, not an HTML-serving
  surface, and a CSP here would just be noise with nothing to actually constrain
  (the interactive OpenAPI docs at `/docs` are the one HTML page this API serves,
  and FastAPI's own bundled Swagger UI needs inline scripts that a strict CSP would
  break for no real security gain in a local-dev tool).

## Why API key, not JWT

The brief says "API-key/JWT". This project has no user accounts, no login flow, and
no per-user permission model to differentiate — it's a single-tenant service API. A
JWT's actual value (carrying claims about *who* is calling and *what they're
allowed to do*, without a database round-trip) has nothing to attach to here; a
shared API key is the right-sized mechanism for "is this caller allowed to use this
service at all," which is the actual question this project needs answered. Adding
JWT issuance/verification/refresh machinery for a binary allow/deny check would be
solving a problem this project doesn't have — the same reasoning that kept RQ over
Celery in Phase 16.

## Rate limiting: Redis-backed, fixed window, fails open

`app/middleware/rate_limit.py` uses `INCR`+`EXPIRE` on a
`ratelimit:{client}:{minute-window}` Redis key — a fixed window, not a sliding
window or token bucket. A fixed window is honestly not the most precise algorithm
(it allows up to 2x the configured rate across a window boundary, in the worst
case), but it's simple, well-understood, and correct enough for what this project
needs: a coarse abuse guard, not a precisely metered billing system. Client identity
is the `X-API-Key` header when present, else the request's IP — meaning if
`API_KEY` is unset, rate limiting falls back to per-IP, which is the right behavior
for a still-unauthenticated local/dev deployment.

**Fails open, not closed**: if Redis is unreachable when rate limiting is enabled,
the middleware logs a warning and lets the request through rather than returning an
error. A rate limiter is a hardening measure; treating its own dependency outage as
grounds to take the whole API down would make the API *less* available specifically
because of a feature meant to protect it — the wrong tradeoff. This mirrors Phase
17's caching layer, which also degrades gracefully rather than failing hard when
Redis is the thing that's unavailable — though caching's `CacheNotConfiguredError`
is raised (a config *error* — Redis was never set up) while rate limiting's
Redis-unreachable case is caught and swallowed (a runtime *outage* of something
that was configured) — different failure modes, handled differently on purpose.

## A real bug this phase's own tests caught: `API_KEY=` (empty) isn't `None`

The first test run locked every non-exempt request out with a 401 by default —
`.env` (this project's real local dev file, not `.env.example`) has `API_KEY=`
present but empty, and `require_api_key`'s first version checked
`if settings.api_key is None: return`. Pydantic-settings reads a present-but-empty
env var as `""`, not `None`, so the guard didn't fire and every request without a
matching key got rejected — with no key configured anywhere. Fixed to `if not
settings.api_key: return`, matching the falsy-check convention this codebase
already uses for `anthropic_api_key` (`llm_client.py`) and `pinecone_api_key`
(`retrieval/factory.py`) — both already got this right; the new `api_key` check
didn't, until the test suite caught it immediately. Left in as a concrete example
of why this phase writes real tests before declaring the feature done rather than
after.

## Testing

`tests/api/test_security.py` covers: security headers present on every response;
no auth required by default; `/health`/`/ready` never require a key even when one's
configured; missing/wrong/correct API key produce 401/401/200; rate limiting
disabled by default allows unlimited requests in a test run; a mocked Redis
counter produces a 429 once the configured limit is exceeded; the rate limiter
fails open (200, not 500 or 429) when Redis raises a connection error; and
`/health` stays exempt from rate limiting even under a saturated mock counter.
Redis interactions are mocked here (unlike Phase 16/17's real-Redis integration
tests) because rate limiting's actual logic under test is the *fixed-window
counting and threshold comparison*, not Redis client behavior itself — Phase
16/17 already have real-Redis coverage proving this project's Redis integration
generally works; duplicating that here would test the same thing twice instead of
testing what's actually new.

## What Phase 18 did not build

- **Per-endpoint rate limits** (e.g. a stricter limit on `/query` than
  `/documents/upload`) — one global `RATE_LIMIT_REQUESTS_PER_MINUTE` for now; no
  evidence yet that endpoints need different budgets.
- **API key rotation/expiry/multiple keys** — `API_KEY` is a single shared secret,
  matching this project's single-tenant scope. A multi-key or per-client scheme
  would need a place to store and manage keys (a new DB table, an admin
  surface) that nothing in this project currently needs.
- **Broader input-sanitization work beyond what Phase 14 already covered** — Phase
  14's adversarial suite already tested path traversal (found and fixed), control
  characters, SQL-injection-shaped strings (confirmed safe via SQLAlchemy's
  parameterized queries), and unicode/RTL content. Nothing new surfaced in this
  phase's review of the request/response surface that Phase 14 hadn't already
  addressed or that genuinely needed more than the security headers above.
