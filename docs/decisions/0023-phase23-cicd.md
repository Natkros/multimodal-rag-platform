# ADR 0023: Phase 23 CI/CD

## Audit first: CI already did the core job

`.github/workflows/ci.yml` has run lint, type-check, tests, and a Docker build on
every push/PR since Phase 1. This phase's job was closing real gaps in that
pipeline, not rebuilding it — same audit-first approach as Phase 15/21.

## Coverage reporting and a real fail-under gate

`pytest tests/ --cov=app --cov-report=term-missing --cov-report=xml
--cov-fail-under=90` — the `--cov-fail-under=90` threshold is a genuine regression
gate, not a decorative number: Phase 22 measured 95% real coverage, so 90% leaves a
5-point buffer for normal fluctuation while still failing the build if coverage
drops meaningfully (e.g. a new module shipped with no tests at all). The XML report
is uploaded as a build artifact (`actions/upload-artifact@v4`) so it's inspectable
per-run without needing a third-party coverage service (Codecov etc.) this project
has no account for — adding a dependency on an external SaaS for this would be
solving a problem ("where do I look at coverage trends") this project doesn't
currently have, the same reasoning that's kept several other phases from adding
infrastructure with no real consumer yet.

## A real, previously-hidden bug this phase's own investigation found: mypy has been silently failing outright

Running `mypy app --ignore-missing-imports` locally (not just trusting the `|| true`
in CI, which was masking whatever mypy actually did) revealed it doesn't get past
the *first* file: `numpy`'s own bundled `.pyi` type stubs (numpy 2.3+) use PEP 695
`type` statement syntax, which mypy refuses to parse when checking against this
project's configured `python_version = "3.11"` target (that syntax requires 3.12+).
This means **mypy has not completed a single successful check of this project's own
code** since numpy crossed that version boundary — `|| true` silently converted a
total parse failure into "step passed," which is exactly the kind of unverified
claim ("we have type checking") this project's rules exist to prevent. Two fixes
were attempted and rejected before settling on disclosure:

- **`[[tool.mypy.overrides]] module = "numpy.*"` with `follow_imports = "skip"`
  and `ignore_errors = true`**: didn't work. This is a *syntax* error at parse
  time, before mypy applies any per-module override — overrides only affect
  semantic checking of an already-parsed file, not whether mypy can parse it at
  all as a dependency during module discovery.
- **Bumping `python_version` to `"3.12"`**: rejected without trying, not because it
  wouldn't fix the parse error (it would), but because this project's actual
  runtime target is Python 3.11 (`Dockerfile`: `python:3.11-slim`; CI:
  `python-version: "3.11"`) — silently raising the type-checker's target version
  would let this project's own code start using 3.12+-only syntax without mypy
  ever flagging it as incompatible with the Python version it actually runs on.
  That's a worse failure mode than the one being fixed.

Left as `|| true` (unchanged from before, but now with the *real* reason stated in
both `ci.yml` and here, not a vague "non-blocking during early phases" comment that
was accurate in Phase 1 and stale by Phase 23). A real fix — pinning numpy to a
pre-2.3 release, or waiting for a mypy release that handles this stub compatibility
case — wasn't attempted blind: pinning `numpy` risks a version conflict with
`sentence-transformers`/`torch` that this session couldn't verify without
reinstalling and re-testing the entire dependency tree, which is a bigger, riskier
change than this phase's stated scope.

## `docker compose config --quiet` added to the build job

Validates `docker-compose.yml`'s YAML structure and env-var interpolation without
needing to actually build or start anything — catches a malformed compose file
(e.g. Phase 16/17's env var additions had a typo) cheaply, before the two full
image builds that follow it.

## What Phase 23 deliberately did not add: a deploy job

The brief lists "CI/CD" as Phase 23 and cloud deployment as Phase 24 — a fake or
stub "deploy" job in `ci.yml` with no real cloud target, no credentials, and
nothing to deploy *to* would be pure theater: a green checkmark that deploys
nothing, misleading in exactly the way this project's rules forbid ("never fabricate
metrics" extends to never fabricating a deployment pipeline that doesn't deploy
anything real). `docs/deployment.md` already states plainly that no cloud
deployment exists; adding a job here that implies otherwise would contradict that
file. A real deploy job is exactly what Phase 24 is for, once there's an actual
target to deploy to.
