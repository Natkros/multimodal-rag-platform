# ADR 0028: Phase 28 Admin / Evaluation Dashboard

## Extending the existing frontend, not building a second one

The brief's Phase 28 goal is an admin/evaluation dashboard. This project already
has a Streamlit UI (`frontend/app.py`, Phase 1) talking to the API over HTTP with
no business logic of its own — the same architecture applies directly to an admin
view, so this phase adds a fourth tab (`Upload`, `Ask`, `Documents`, **`Admin`**)
rather than standing up a separate app with its own deployment story.

## Two genuinely different data sources, two genuinely different reliability guarantees

The Admin tab has two sections, and they were deliberately not treated the same
way:

1. **Live metrics** (`GET {API_BASE_URL}/metrics`, Phase 19's Prometheus
   endpoint) — parsed with a ~15-line regex-based Prometheus text-format reader
   (no new dependency justified for something this small) into
   `http_requests_total` by route/status, Phase 17's cache hit/miss counts, and
   Phase 18's rate-limit rejection count. This **always works** on any deployment
   that has the frontend able to reach the API at all — it's the same HTTP call
   every other tab already makes.
2. **Evaluation report history** (reading `evaluation/reports/*.json` from this
   process's own filesystem) — this **does not always work**. It requires the
   frontend process/container to actually have that directory available, which is
   true in `docker-compose.yml` (this phase added a read-only volume mount,
   `./evaluation/reports:/app/evaluation_reports:ro`, plus `EVAL_REPORTS_DIR`) but
   is not guaranteed on every deployment target — Phase 24's `render.yaml`, for
   instance, has no equivalent mount, and wasn't given one this phase (adding a
   shared-storage mechanism for this one dashboard feature would be a
   disproportionate change to a Blueprint already scoped down in ADR 0024). The UI
   handles the missing-directory case explicitly (`EVAL_REPORTS_DIR.is_dir()`
   check → an honest "not accessible from this process" message), not a crash or
   a silently empty table that looks like "no reports exist yet."

## Verified in a real browser, not just read for syntax correctness

Unlike the rest of `frontend/`, which has no test coverage in this project
(Streamlit apps aren't part of `pytest`'s collection — a pre-existing, accepted
gap, not something this phase tried to fully close), this feature was verified by
actually running it: a real `uvicorn` API process and a real `streamlit run`
process, both started locally, driven through the built-in browser tool. The
screenshots confirm real data flowing end-to-end — the HTTP-requests-by-route
table showing actual recorded requests, and the evaluation-report-history table
listing this repo's real `evaluation/reports/*.json` files (including
Phase 25/26's `load_test_*.json` and `mmr_comparison_*.json` reports) with
correct `throughput_req_per_s`/`error_rate` values pulled out of the load-test
reports' schema.

## A real, disclosed limitation found during that verification: report schemas aren't uniform

`evaluation/reports/` holds several genuinely different JSON shapes accumulated
across phases: a flat single-config report (`dense_baseline_*.json`), a
multi-config comparison report where the interesting numbers are nested one level
deeper under each named config (`reranking_comparison_*.json`,
`mmr_comparison_*.json`, `retrieval_mode_comparison_*.json`), and a load-test
report with entirely different top-level fields (`throughput_req_per_s`,
`error_rate`). The dashboard's `recall@5`/`mrr` columns only populate for the flat
single-config shape — verified live, the multi-config comparison reports show
`None` in those columns (their real numbers are inside nested per-config objects
the table's simple `summary.get("metrics", summary)` lookup doesn't reach), while
the file name, and (for load-test reports) throughput/error-rate, always display
correctly regardless of shape. Building a full per-report-type schema parser to
close that gap was judged not worth it for what remains a lightweight dashboard
view — the file list and headline load-test numbers are the primary value, and
the raw JSON is always one click away in `evaluation/reports/` for anyone who
needs the nested comparison numbers. Disclosed here and left as-is, not silently
shipped as if it handled every report type uniformly.

## What Phase 28 did not build

- **No auth on the Admin tab itself** — the Streamlit frontend has no
  authentication layer at all (Phase 18's `API_KEY` protects the *API*, not this
  UI); adding a separate auth mechanism just for one tab of a small internal tool
  would be disproportionate, and this is consistent with the rest of `frontend/`'s
  scope.
- **No write actions from the dashboard** (triggering a re-run of `scripts/run_eval.py`
  or `compare_*.py` from the UI) — read-only reporting was the actual Phase 28
  ask; turning it into a job-launcher would need the Phase 16 queue wired up to a
  new endpoint, out of scope here.
- **No historical trend charts** (e.g. Recall@5 over time across reports) — would
  need the schema-normalization work described above first; charting inconsistent
  data would risk implying a trend line means something it doesn't.
