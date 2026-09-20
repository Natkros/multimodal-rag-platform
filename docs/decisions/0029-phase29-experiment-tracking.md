# ADR 0029: Phase 29 Experiment Tracking

## No MLflow/W&B — this project's actual problem is smaller than that

Since Phase 1, `evaluation/reports/` has accumulated JSON reports from
`scripts/run_eval.py`, every `compare_*.py`, `profile_pipeline.py`, and
`load_test.py` — 14 reports by the time this phase started, each with its own
timestamped filename, and Phase 28 already built a UI to browse them. What was
still missing: **which commit produced a given number**. A hosted experiment
tracker (MLflow, Weights & Biases) solves problems this project doesn't have —
multiple collaborators comparing runs across a team, hyperparameter sweep
visualization, model registry/versioning for models this project doesn't train.
Adding one would mean a new service dependency (a tracking server, or a SaaS
account) for a single-developer project whose actual need is "trace this number
back to the code that made it," which git already answers if the report just
records the commit hash at write time.

## `experiment_log.py`: one shared helper, wired into every report-writing script

`app/services/evaluation/experiment_log.py::write_experiment_report()` wraps
whatever a script was already going to write under an `"experiment"` key
(`git_commit`, `git_dirty` — whether the working tree had uncommitted changes at
write time, `generated_at`, `python_version`) and writes it to the exact same
`evaluation/reports/{name_prefix}_{timestamp}.json` path convention every script
already used — Phase 28's dashboard and this phase's `scripts/list_experiments.py`
both just glob `*.json`, so nothing downstream needed to change to keep finding
these. `scripts/run_eval.py` and `scripts/load_test.py` were switched to call it
instead of their own ad-hoc `json.dumps` + `write_text` — real duplicated logic
removed, not just new logic added alongside old.

`git_dirty` matters as much as `git_commit`: a report generated against a dirty
working tree is honestly *not* fully reproducible from the commit alone — someone
re-running the exact commit later would need to know that, rather than silently
trusting a hash that doesn't tell the whole story.

## Old reports aren't retroactively rewritten

The 14 reports that existed before this phase have no `"experiment"` key —
`scripts/list_experiments.py` shows them plainly as `"pre-Phase-29 (no metadata)"`
rather than backfilling a fake commit hash (guessed from file mtime, or just
whatever `HEAD` happens to be *now*) that would misrepresent what commit actually
produced those specific numbers. Only `run_eval.py` and `load_test.py` were
migrated this phase, not every `compare_*.py` script — the pattern is proven
working end-to-end (verified: `scripts/list_experiments.py` run against this
project's real `evaluation/reports/` correctly separates old, unmigrated reports
from what a newly-written one will look like), and migrating the remaining
scripts is a mechanical, low-risk follow-up rather than something that needed to
block this phase.

## Testing

`tests/unit/test_experiment_log.py` covers: `experiment_metadata()` returns all
four expected fields; run against this project's own real git repo, `git_commit`
is a genuine 40-character SHA (not a mocked stand-in — proving the subprocess call
actually works here, not just that the function has the right shape); a
`FileNotFoundError` (git not installed/not a repo) degrades to `None` fields
rather than crashing; `write_experiment_report()` wraps the given report,
creates the target directory if missing, and names the file with the expected
prefix.

## What Phase 29 did not do

- **No migration of `compare_chunking_strategies.py`, `compare_retrieval_modes.py`,
  `compare_reranking.py`, `compare_mmr.py`, or `profile_pipeline.py`** to the new
  helper — mechanical follow-up work, not done blind this phase to keep the change
  reviewable and because `run_eval.py`/`load_test.py` already prove the pattern
  works across two different report shapes (a flat eval report and a
  latency/throughput report).
- **No historical backfill** of git metadata for old reports — see above.
- **No dashboard change** — Phase 28's Admin tab already lists every file in
  `evaluation/reports/`; the new `"experiment"` key is additive JSON that existing
  `summary.get(...)` lookups simply don't reach, so nothing broke and nothing
  needed to change there this phase (a future pass could surface `git_commit` in
  that table, not done here to keep this phase's scope to the tracking mechanism
  itself).
