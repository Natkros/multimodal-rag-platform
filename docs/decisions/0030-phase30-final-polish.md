# ADR 0030: Phase 30 Final Polished Demo

## What "final polish" means for a 30-phase incremental build

29 phases each added something real and committed it with its own tests and ADR.
What accumulates across 29 incremental changes, even when each one is individually
careful, is documentation drift: numbers that were true when written (test counts,
feature lists scoped to "Phase 0-N") stop being the current truth a few phases
later, and nobody's job in any single phase was to go back and fix them. Phase
30's actual scope: read the whole README and repo tree as a first-time user would,
verify the parts that claim to work still do, and fix what's drifted — not add a
31st feature.

## A real bug this phase's own verification found: the Quickstart itself was broken

README's Quickstart says: `cp .env.example .env`, then `uvicorn app.main:app
--reload`. This phase actually ran that exact sequence (a fresh environment
simulation: load only `.env.example`'s variables, nothing from this project's own
working `.env`) rather than trusting that it worked because the individual
features it exercises were all tested in isolation. It crashed immediately:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
context_max_chunks_per_document
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='', input_type=str]
```

`.env.example` ships `CONTEXT_MAX_CHUNKS_PER_DOCUMENT=` — present, empty, the same
convention used for `API_KEY=`/`ANTHROPIC_API_KEY=`/`PINECONE_API_KEY=` (a
discoverable line for a fresh clone to fill in, meaning "unset"). Those work
because they're `str | None` fields, and `""` is already a valid string.
`context_max_chunks_per_document: int | None = Field(default=None)` is the one
numeric-optional field with the same empty-value convention in `.env.example`, and
pydantic-settings tries to parse `""` as an integer rather than treating it as
absent — a `ValidationError`, not a graceful fallback to the field's own `None`
default. **This means every person who ever followed this README's Quickstart
exactly as written would have hit a crash on the very first command** — caught
only because this phase actually ran it instead of re-reading the code and
concluding it should work.

Fixed with a `field_validator(mode="before")` on `context_max_chunks_per_document`
that maps `""` to `None` before pydantic's type validation runs
(`app/core/config.py`). Verified three ways, not just unit-tested in isolation:
`tests/unit/test_config.py::test_env_example_produces_a_bootable_config`
reproduces the exact failing env var; and a real `uvicorn` process was booted
end-to-end against `.env.example`'s literal values (no project-specific `.env`
overrides) and confirmed to serve `/health`, `/ready`, accept a real document
upload, and complete real ingestion (`processing_status: "INDEXED"`,
`chunk_count: 2`) — the whole golden path, not just "the process didn't crash."

## Documentation drift fixed

- `README.md` §3's header said "Features (current — Phase 0-12)" — accurate when
  written during Phase 12, stale for the 18 phases since. Updated to Phase 0-29,
  with feature bullets added for Phases 16-19/26/28/29 that had never been
  reflected in the product-facing feature list (they were documented in §9/§11's
  narrative sections, but the feature list itself hadn't been touched since
  Phase 12).
- Testing section said "310+ tests" — the real, current number (331) was one
  `pytest` run away the whole time; updated to state it exactly rather than hedge
  with "+".
- Repository Structure listed `docker/, Dockerfile, docker-compose.yml` — `docker/`
  was an empty, untracked leftover directory with nothing in it (confirmed via
  `find docker -type f` returning nothing, then removed); the listing also never
  mentioned `workers/` (Phase 16) or `render.yaml`/`.dockerignore` (Phases 21/24).
  Updated to reflect the actual current tree.
- Roadmap table's Phase 30 row (this phase) filled in.

## What Phase 30 did not do

- **No new features.** Consistent with what this phase is actually for — verifying
  and correcting, not extending.
- **No rewrite of historical ADRs or measured numbers** (Phase 6/7's 12-question
  baseline figures, etc.) — those are accurate records of what was measured *at
  that point*, not claims about current state, and rewriting them would destroy
  the historical record this project's own rules value (every ADR explains *why*,
  and changing the numbers after the fact would erase the "why" they were measuring
  against).
- **No attempt to close Phase 13's 57/100-300 evaluation-dataset gap or Phase 24's
  undeployed cloud Blueprint** — both are honestly disclosed, reasoned-through
  states from their own phases, not oversights this phase should paper over by
  quietly extending scope beyond "final polish."
