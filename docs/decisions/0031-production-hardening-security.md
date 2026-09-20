# ADR 0031: Production Hardening — Security Pass

## Scope

Requested directly by the project owner as part of a "bring this to production
level" pass, beyond the original 30-phase specification. This ADR covers the
security-specific findings; dataset expansion, general polish, and the live
deployment are each their own follow-up work covered separately (see README's
Roadmap section for the running list, and ADR 0032 for the deployment attempt).

## Real gap found: unhandled exceptions were never logged server-side

`app/main.py` had no registered exception handler. FastAPI's own default
(`debug=False`, no custom handler) already does the right thing for the *client*
— it returns a generic `Internal Server Error` without leaking a stack trace or
file paths. But it does this silently: nothing about a genuine 500 was ever
written to this project's own logs, meaning a real production incident would have
been invisible to anyone operating the service, discoverable only by a user
complaint with no way to correlate it to anything in the logs.

Added `@app.exception_handler(Exception)` in `create_app()`: every unhandled
exception is now logged server-side with its full traceback (via
`logger.exception(...)`, which is safe — it writes to this project's own log
stream, never returned in the HTTP response) and assigned a random `error_id`
(a UUID) that *is* returned to the client alongside the generic message. This
gives operators a way to find the exact incident in logs from a user's bug
report, without ever exposing internals over the wire. Verified with a dedicated
test that deliberately triggers an unhandled exception containing a fake secret
path and asserts the response body contains neither the path, the exception type
name, nor the word "Traceback."

## Real gap found: no HSTS header

`SecurityHeadersMiddleware` (Phase 18) set `X-Content-Type-Options`,
`X-Frame-Options`, and `Referrer-Policy`, but not `Strict-Transport-Security`.
Added `Strict-Transport-Security: max-age=31536000; includeSubDomains`,
unconditionally — per the HSTS specification, a browser ignores this header
entirely when received over plain HTTP, so it has zero effect on local
development (`http://localhost`) and only takes effect once this service
actually sits behind TLS (Render's default HTTPS termination, or any production
reverse proxy), which is exactly when it matters.

## Real gap found: DOCX uploads had no decompression-bomb guard

A `.docx` file is a zip archive. Neither Python's `zipfile` module nor
`python-docx` protects against a decompression bomb — a small, crafted upload
that expands to gigabytes in memory once opened. `MAX_UPLOAD_SIZE_BYTES` (Phase
1) only caps the *compressed* upload size, which does nothing against a file
engineered for a very high compression ratio.

`app/services/extraction/loaders.py::_reject_if_zip_bomb()` inspects each zip
entry's *declared* size and compression ratio directly from the archive's
central directory — a cheap operation that doesn't require decompressing
anything — and rejects the file *before* `DocxDocument()` ever touches the
content if either the total declared uncompressed size exceeds 300MB, or any
single entry's expansion ratio exceeds 100:1. Tested with a real crafted zip
bomb (a single entry of 50MB of zero bytes, which DEFLATE compresses to almost
nothing) and a second case using many low-ratio entries whose *combined* size
still exceeds the cap, confirming the guard checks the running total, not just
one entry in isolation. A third test confirms an ordinary, real `.docx` is
completely unaffected by the new guard.

## Real gap found: unpinned dependencies (`>=` with no upper bound)

`requirements.txt` specifies every dependency as `>=`, with no upper bound —
meaning a fresh `pip install` six months from now could silently resolve a
newer major version of any transitive dependency, including one with a breaking
change or a supply-chain compromise, with no signal that anything changed. This
matters most for the Docker image, which is a long-lived artifact rebuilt and
redeployed independently of when the source code last changed.

Generated `requirements.lock.txt` and `requirements-docker.lock.txt` via
`pip-compile` (pip-tools), pinning every dependency (direct and transitive) to
an exact, currently-tested version. `requirements-docker.lock.txt` was
hand-assembled rather than fully `pip-compile`d: `psycopg2-binary` has no
prebuilt wheel for this development machine's Python version/platform, so
`pip-compile` cannot resolve it locally even though it installs correctly
inside the Linux-based Docker image — it has no sub-dependencies of its own, so
appending its pin by hand to the `pip-compile`-generated base lock is a safe,
correct construction, not a guess. `Dockerfile` now installs from
`requirements-docker.lock.txt` instead of the loose `requirements-docker.txt`.
`requirements.txt`/`requirements-docker.txt` remain the human-edited source of
intent (what a contributor changes when adding a dependency); the `.lock` files
are regenerated deliberately when that happens, not on every build.

## What was checked and found already correct

- `MAX_IMAGE_PIXELS` (Pillow's own decompression-bomb guard for images) is
  intact at its library default (~89.5 million pixels) — not disabled anywhere
  in this codebase.
- No `debug=True` anywhere, and no logging statement anywhere writes an API key,
  password, or other secret value.
- CORS defaults to an explicit origin (`http://localhost:3000`), never a
  wildcard combined with credentials.

## Docker verification: attempted again, same structural result as ADR 0021

Per ADR 0021, this development sandbox has no working Docker daemon. This pass
tried again, twice, specifically to see whether the earlier failure was a
transient timing issue rather than a hard limitation. It is not: Docker
Desktop's own log shows its backend process (`com.docker.backend.exe`) launches
successfully, runs for approximately three and a half minutes, and then exits on
its own — consistent with a genuine, structural incompatibility in this sandbox
(most likely missing WSL2/Hyper-V virtualization support), not a slow cold
start. No further retries are planned; CI's `docker-build` job remains this
project's actual, continuously-run build verification, as already stated in
ADR 0021.

## What this pass did not do

- No secrets-scanning tool (e.g. `gitleaks`, `truffleHog`) was added to CI —
  a real, worthwhile addition, but scoped to a future CI-focused pass rather
  than bundled into a security-code-changes pass, to keep this ADR's diff
  reviewable as one coherent change.
- No Content-Security-Policy header — unchanged reasoning from ADR 0018: this
  is a JSON API, not an HTML-serving surface (aside from the auto-generated
  `/docs` Swagger UI, which needs inline scripts a strict CSP would break for no
  real security gain in what is, even in production, an internal/operator-facing
  page).
