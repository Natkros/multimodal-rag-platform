# Multimodal RAG Platform

A production-grade Retrieval-Augmented Generation platform for heterogeneous enterprise
documents — built incrementally, phase by phase, with a measured baseline before every
claimed improvement. This README reflects **actual, current** repo state; see
[Roadmap](#roadmap--phase-status) for what's built vs. planned.

## 1. Project Overview

Enterprise knowledge lives in PDFs, Word documents, HTML pages, scanned documents,
spreadsheet-style tables, and diagrams — not just clean text. This platform ingests
that heterogeneous corpus, indexes it for both dense (embedding) and sparse (BM25)
retrieval, and answers natural-language questions with page-level citations, abstaining
explicitly when it lacks evidence rather than guessing. It is built as a real service
(FastAPI + Postgres + a pluggable vector store), not a notebook.

## 2. Architecture

See [docs/architecture.md](docs/architecture.md) for the full system, sequence,
ingestion/retrieval, and deployment diagrams (Mermaid). Summary:

```
Upload → validate/hash → extract → normalize → chunk → embed → index (vector store)
Query  → embed → retrieve → (rerank*) → build context → LLM → cite → answer
```
`*` reranking ships in Phase 7 (opt-in, off by default — see §8b).

## 3. Features (current — Phase 0–12)

- Upload PDF / TXT / Markdown / DOCX / HTML / images; idempotent via content-hash
  dedup (`409` on repeat upload)
- Three chunking strategies, measured against each other (see §8): `fixed` (naive
  token windows), `recursive` (structure-aware, splits on headings/paragraphs — the
  default), and `semantic` (embeds sentences, splits on similarity drift) — DOCX and
  HTML are normalized into the same heading-marked text the chunker already
  understands, so no format-specific chunking logic
- Text normalization step (Unicode NFC, line-ending/whitespace canonicalization)
  between extraction and chunking
- **OCR** (Tesseract) for scanned PDFs (no text layer → rendered page images → OCR'd)
  and images with visible text — genuinely tested against installed OCR binaries, not
  mocked (see [ADR 0004](docs/decisions/0004-phase4-multimodal-processing.md))
- **Structured table extraction** (PDF via pdfplumber, DOCX via python-docx): tables
  become their own searchable chunks (`content_type="table"`) with headers/rows
  preserved verbatim, never flattened into surrounding text
- **Visual descriptions**: images with no OCR-extractable text (photos, diagrams) get
  a caption from a vision-capable LLM when one is configured, making even a
  wordless image searchable; with neither OCR text nor a caption available, an image
  is still cataloged (format/dimensions) without being searchable — a valid outcome,
  not a failure
- `GET /documents/{id}/chunks` exposes chunk-level provenance — `content_type` and
  `extra_metadata` (table headers/rows, image OCR text/caption)
- **Multimodal retrieval routing**: a question's wording ("compare the two tables",
  "what does the chart show") routes retrieval to `table`/`image`/`text` chunks
  specifically instead of blending everything by score; `POST /query` surfaces which
  content type(s) it matched (`retrieval.matched_content_types`) and each source's
  `content_type`, so routing is verifiable, not just claimed (see
  [ADR 0005](docs/decisions/0005-phase5-multimodal-retrieval.md))
- Staleness detection: documents indexed under a chunking strategy or embedding model
  that no longer matches current config are flagged `REINDEX_REQUIRED` via
  `POST /documents/check-staleness`
- **Hybrid search** (dense + BM25): a local BM25 sparse index (`rank_bm25`) is kept in
  sync alongside the vector store at ingestion time; `RETRIEVAL_MODE=hybrid` fuses both
  via Reciprocal Rank Fusion (default) or a configurable weighted combination —
  measured to raise MRR 0.750→0.875 and nDCG@5 0.812→0.906 over dense-only on this
  corpus, at ~2.8x retrieval latency (see §8 and
  [ADR 0006](docs/decisions/0006-phase6-hybrid-search.md))
- **Reranking** (opt-in, `RERANKER_ENABLED=true`): a local cross-encoder
  (`cross-encoder/ms-marco-MiniLM-L-6-v2`) rescoring a wider candidate pool (default
  30) down to the final top-K — measured honestly, not assumed to help: on this
  corpus it made ranking *very slightly worse* (MRR 0.875→0.858) at ~42x latency, a
  real negative result reported as such (see §8 and
  [ADR 0007](docs/decisions/0007-phase7-reranking.md))
- **Query intelligence** (opt-in, `QUERY_INTELLIGENCE_ENABLED=true`): follow-up
  questions ("what about Q2?") get rewritten into self-contained form using
  persisted conversation history; multi-part/comparison questions get decomposed
  into sub-questions, each retrieved and tracked separately
  (`query_intelligence.retrieval_trace`); a question naming a specific indexed
  document auto-scopes retrieval to it. Ambiguous/short/follow-up/multi-part
  detection is deterministic (no LLM call); rewriting/decomposition/expansion are
  LLM calls that fail soft to a no-op when unconfigured — see
  [ADR 0008](docs/decisions/0008-phase8-query-intelligence.md)
- **Conversation persistence** (Phase 12): `conversations`/`messages` tables record
  every turn of any `/query` request that supplies a `conversation_id`, independent
  of whether query intelligence is enabled — replaces Phase 8's process-local,
  restart-losing in-memory store; each stored assistant message carries the
  `chunk_id`s it cited for provenance (see
  [ADR 0012](docs/decisions/0012-phase12-conversational-rag.md))
- **Context engineering** (opt-in beyond Phase 1's dedupe+budget packing): a
  relevance floor drops weak candidates, a per-document diversity cap stops one
  source from crowding out others, deterministic truncation ("compression") caps
  any single oversized chunk instead of letting it eat the whole token budget —
  `retrieval.source_distribution` is always reported (see
  [ADR 0009](docs/decisions/0009-phase9-context-engineering.md))
- **Citation validation** (on by default): every cited sentence in an answer is
  checked against its cited chunk(s) — word-overlap ratio plus exact number/proper-
  noun matching, catching fabricated figures or names even when the surrounding
  wording overlaps heavily with the source; `citation_validation.citation_correctness`
  in the `/query` response (see
  [ADR 0011](docs/decisions/0011-phase11-citation-engine.md))
- Grounded generation with configurable confidence thresholds
  (`GROUNDING_CONFIDENCE_THRESHOLD` to abstain, `GROUNDING_HIGH_CONFIDENCE_THRESHOLD`
  for the "high"/"low" label) and explicit uncertainty-hedging for partial/
  conflicting evidence (see [ADR 0010](docs/decisions/0010-phase10-grounded-generation.md))
- Configurable local embedding model (`sentence-transformers`, no API key required)
- Vector store behind an abstraction — `local` (numpy, zero-setup) or `pinecone`
- Dense (default) or hybrid retrieval → grounded generation (Anthropic Claude) →
  numbered citations
- Explicit abstention when retrieval confidence is below threshold
- Async ingestion (background task) with pollable job status
- `/health`, `/ready`, structured JSON errors, request-level latency breakdown
- Deterministic retrieval-metrics harness (`scripts/run_eval.py`) with a seed dataset
- Full test suite (unit / integration / API) — see [Testing](#testing)
- `docker compose up` runs the full stack locally

## 4. Technology Stack & Why

| Component | Choice | Why |
|---|---|---|
| API | FastAPI | async-native, typed, OpenAPI for free |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (configurable) | runs locally, no API key needed to develop/test; swappable via `EMBEDDING_PROVIDER` |
| Vector store | Pinecone (prod) / in-process cosine store (dev, default) | brief names Pinecone; abstraction means CI/onboarding never needs a live account — see [ADR 0001](docs/decisions/0001-phase1-stack-choices.md) |
| Sparse retrieval | `rank_bm25` (BM25Okapi), local, disk-persisted | the brief names BM25 itself, not a hosted search engine — no cloud/local split needed the way the vector store had one; see [ADR 0006](docs/decisions/0006-phase6-hybrid-search.md) |
| Reranking | `sentence-transformers` `CrossEncoder` (`ms-marco-MiniLM-L-6-v2`) | local, no per-request API cost — same reasoning as embeddings/OCR/BM25; see [ADR 0007](docs/decisions/0007-phase7-reranking.md) |
| LLM | Anthropic Claude, model configurable | strong grounded-generation instruction following |
| DB | PostgreSQL (prod) / SQLite (dev, tests) | same SQLAlchemy models, zero-setup local dev |
| PDF extraction | `pypdf` | lightweight, pure-Python, no system dependencies |
| DOCX extraction | `python-docx` | reads paragraph styles (for heading detection) and tables directly from the OOXML structure |
| HTML extraction | `beautifulsoup4` + `lxml` | robust real-world HTML parsing (malformed markup, scripts/styles to strip) |
| Image metadata | `Pillow` | format/dimension extraction, and OCR preprocessing |
| OCR | `pytesseract` (Tesseract) + `pdf2image` (Poppler) | industry-standard, free, local OCR — no API key or per-page cost; system binaries, not pip packages, see [ADR 0004](docs/decisions/0004-phase4-multimodal-processing.md) |
| Table extraction | `pdfplumber` (PDF) + `python-docx` (DOCX) | structured headers/rows, not flattened text — pdfplumber specifically for its table-detection support pypdf lacks |
| Visual descriptions | Anthropic Claude vision (same LLM client as generation) | reuses the existing LLM integration rather than adding a second model/provider just for captioning |
| Containerization | Docker / Compose | one-command local stack |
| Tests | pytest + FastAPI TestClient | fast, no external services required |

## 5. RAG Pipeline

`ingestion → normalization → chunking → embedding → retrieval → (reranking) → generation`
— see [docs/architecture.md](docs/architecture.md) §3–4 for sequence diagrams and
[docs/api.md](docs/api.md) for the exact request/response contracts.

## 6. Multimodal Pipeline

`text → OCR → tables → images → unified representation → indexing`. Scanned PDFs (no
text layer) fall back to rendering each page and running Tesseract OCR over it. Images
run OCR first; if that finds real text they become a normal searchable chunk, and if
not, a vision-LLM caption is attempted (when an LLM is configured) as a second chance.
An image with neither OCR text nor a caption is still cataloged (format, dimensions,
content-hash dedup) without being searchable — a valid, tested outcome, not a failure.
PDF/DOCX tables are extracted as structured chunks (`content_type="table"`, headers
and rows preserved verbatim in `extra_metadata`) rather than flattened into
surrounding text. On the retrieval side (Phase 5), a query's wording routes search to
text/table/image chunks specifically when it clearly points that way (`"compare the
two tables"` → table-only; `"what does the chart show?"` → image-only), falling back
to an unrestricted blended search otherwise — see
[ADR 0005](docs/decisions/0005-phase5-multimodal-retrieval.md). **Not yet built**:
layout analysis / bounding boxes (no page-object detection model is wired up — see
[ADR 0004](docs/decisions/0004-phase4-multimodal-processing.md) for why that's
explicitly out of scope so far).

## 7. Evaluation

Method is documented in [docs/evaluation.md](docs/evaluation.md) — every metric states
whether it's **[deterministic]**, **[LLM-as-judge]**, or **[human]**. Phase 1 ships the
retrieval-metrics harness and a baseline report; run it yourself:

```bash
python scripts/run_eval.py --dataset evaluation/datasets/qa_dataset.jsonl --corpus sample_docs
```

Results land in `evaluation/reports/`. No fabricated numbers — the report you get is
whatever your own run produces against the seed dataset in
[evaluation/datasets/qa_dataset.jsonl](evaluation/datasets/qa_dataset.jsonl).

## 8. Baselines

Phase 1 ships **dense-only** retrieval as the baseline. Measured on the 12-question
seed set (10 answerable + 2 deliberately unanswerable — see
[docs/evaluation.md](docs/evaluation.md) for why unanswerable queries are excluded
from Recall/MRR rather than silently averaged in), `all-MiniLM-L6-v2` embeddings,
`local` vector store, top-k up to 10, on this machine:

| System | Recall@5 | MRR | nDCG@5 | Latency p50 |
|---|---:|---:|---:|---:|
| Dense, Phase 1 corpus (4 docs) | 1.00 | 0.875 | 0.906 | 12.7 ms |
| Dense, Phase 4 corpus (8 docs, incl. OCR'd scan + OCR'd image) | 1.00 | 0.750 | 0.812 | 15.0 ms |
| **Hybrid (dense + BM25), Phase 4 corpus** | 1.00 | **0.875** | **0.906** | 37.9 ms |
| Hybrid + Reranker, Phase 4 corpus | 1.00 | 0.858 | 0.893 | 1648.0 ms |

Reproduce: `python scripts/run_eval.py` (full report incl. per-question rows written to
`evaluation/reports/`). Recall@5 of 1.0 on a 10-question seed set is expected and not
impressive by itself — the dataset is small and hand-authored against one corpus; it
exists to prove the harness is wired correctly end-to-end, not as a headline number.
The MRR/nDCG dip between the first two rows is a real, honest finding, not noise:
adding Phase 4's OCR'd scanned PDF and OCR'd chart as genuine retrieval candidates
gives the retriever more chunks that can plausibly rank above the "correct" one for a
few questions. **Hybrid search recovers that entire dip** (§8a) — BM25's exact lexical
matching breaks ties dense embeddings alone couldn't, at ~3x retrieval latency. Adding
a reranker on top (§8b) did **not** help further on this dataset — a genuine negative
result, reported as measured rather than assumed away.

### 8a. Phase 6 — Dense vs. Hybrid (Dense + BM25) Retrieval

Same 12-question seed set, same 8-document corpus, only `RETRIEVAL_MODE` differs
(`rrf` fusion, default `k=60`):

| Mode | Recall@5 | Recall@10 | MRR | nDCG@5 | Latency p50 |
|---|---:|---:|---:|---:|---:|
| dense | 1.000 | 1.000 | 0.750 | 0.812 | 13.6 ms |
| hybrid | 1.000 | 1.000 | **0.875** | **0.906** | 37.9 ms |

Both modes reach perfect Recall@5 — the corpus is small enough that dense alone
already surfaces the right chunk somewhere in the top 5 — so the real signal is
*ranking quality*: hybrid's BM25 component breaks ties dense cosine-similarity alone
can't (exact terms, numbers, codes), moving MRR from 0.750 to 0.875 and nDCG@5 from
0.812 to 0.906. That's a real, measured cost, not free: retrieval latency roughly
tripled (13.6ms → 37.9ms p50) from running two searches plus a fusion step instead of
one. Reproduce: `python scripts/compare_retrieval_modes.py`. Full method, including
why a real bug (RRF's raw scores were too small to clear the grounding confidence
threshold, and a test-isolation gap that let the sparse index leak state between
tests) got caught and fixed while building this: [ADR 0006](docs/decisions/0006-phase6-hybrid-search.md).

### 8b. Phase 7 — Reranking (measured, not assumed)

`RETRIEVAL_MODE=hybrid` held fixed, only `RERANKER_ENABLED` varies
(`cross-encoder/ms-marco-MiniLM-L-6-v2`, candidate pool 30, final top_k 5):

| Config | Recall@5 | MRR | nDCG@5 | Retrieval p50 | Rerank p50 | Total p50 |
|---|---:|---:|---:|---:|---:|---:|
| hybrid, no rerank | 1.000 | **0.875** | **0.906** | 38.6 ms | 0 ms | 38.6 ms |
| hybrid + rerank | 1.000 | 0.858 | 0.893 | 42.9 ms | 1605.1 ms | 1648.0 ms |

**Reranking made ranking quality very slightly worse** here (MRR 0.875→0.858) while
adding ~42x total latency. The project rule is "do not assume reranking improves the
system; prove it experimentally" — this is that proof, and it came back negative.
Likely cause: the reranker is trained on MS MARCO web passage ranking, a different
domain/style than this project's small structured corpus, and hybrid retrieval was
already ranking these 12 questions about as well as a 5-way top-K permits — leaving
the reranker nothing to fix and some domain-mismatch noise to introduce instead. Not a
verdict on cross-encoder reranking in general; a verdict on *this* reranker, on *this*
dataset, at *this* latency. `RERANKER_ENABLED=false` stays the default. Reproduce:
`python scripts/compare_reranking.py`. Full writeup:
[ADR 0007](docs/decisions/0007-phase7-reranking.md).

**Phase 3 — chunking strategy comparison** (`fixed` vs `recursive` vs `semantic`,
measured with content-based relevance since chunk IDs aren't comparable across
strategies — see [docs/evaluation.md](docs/evaluation.md)):

| Strategy | HitRate@5 | Precision@5 | nDCG@5 | MRR | Latency p50 | Ingest+eval wall time |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 1.000 | 0.220 | 0.882 | 0.833 | 12.7 ms | 26.9 s |
| recursive (default) | 1.000 | 0.220 | 0.928 | 0.900 | 13.1 ms | 39.9 s |
| semantic | 1.000 | 0.440 | 0.868 | 0.808 | 20.1 ms | 131.8 s |

`recursive` wins on ranking quality (nDCG/MRR) on this corpus; `semantic` roughly
doubles precision (tighter, more topically-coherent chunks) but costs 3–5x the
ingestion time and ~50% more query latency, since it embeds every sentence and
searches more, smaller vectors. `fixed` trails on every ranking metric. Reproduce:
`python scripts/compare_chunking_strategies.py`.

## 9. Performance

No load-test numbers exist yet (Phase 20/25). Per-request latency breakdown
(`retrieval_latency_ms`, `generation_latency_ms`, `total_latency_ms`) is already
returned by `POST /query` — see [docs/api.md](docs/api.md).

## 10. Failure Handling

Handled and tested today: corrupted/unparseable PDF/DOCX/image, empty file,
unsupported file type, oversized upload, duplicate upload, LLM not configured (`503`,
not a crash), zero retrieval matches (explicit abstention, not a hallucinated answer).
See `tests/api/test_documents.py`, `tests/api/test_query.py`,
`tests/integration/test_ingestion_pipeline.py`,
`tests/unit/test_extraction_loaders.py`. Broader adversarial testing (Phase 14) is not
yet built.

## 11. Security

Current posture is **local-dev only**: no auth, CORS restricted to `localhost:3000` by
default, secrets via environment variables only (`.env` git-ignored, `.env.example`
has no real values), upload size/type validation enforced. API-key/JWT auth, rate
limiting, and input sanitization hardening are Phase 18.

## 12. Deployment

Local: `docker compose up` (see [docs/deployment.md](docs/deployment.md)). **No cloud
deployment exists yet** — that file says so explicitly and will only claim otherwise
once Phase 21/24 actually ship it.

## 13. API Documentation

Full contracts: [docs/api.md](docs/api.md). Interactive OpenAPI docs at
`http://localhost:8000/docs` once the server is running.

```bash
curl -X POST http://localhost:8000/documents/upload -F "file=@sample_docs/acme_employee_handbook.md"
curl -X POST http://localhost:8000/query -H "Content-Type: application/json" \
  -d '{"question": "What is Acme'\''s cancellation policy?"}'
```

## 14. Limitations (honest, current)

- No layout analysis / bounding boxes — table and image chunks carry page-level
  provenance, not pixel coordinates (see [ADR 0004](docs/decisions/0004-phase4-multimodal-processing.md)
  for why this is explicitly deferred rather than half-built)
- Images with no OCR-extractable text and no configured vision LLM are still
  cataloged-only, not searchable — expected, not a bug (see §6)
- A PDF table's content can appear twice in the index (once in its page's ordinary
  text chunk via pypdf, once as its own structured table chunk via pdfplumber) —
  disclosed duplication, not silently hidden (ADR 0004)
- Query→content-type routing (Phase 5) is keyword-based, not an LLM call — it catches
  clear wording ("chart", "table", "the document says") but won't infer intent from
  phrasing that doesn't use those cues; Phase 8's query intelligence is where deeper
  language understanding belongs
- Multi-type queries (e.g. "does the chart match the table?") run one filtered search
  per matched type and merge by score — no vector store here supports a richer
  "OR"/"in" filter, so this is N round-trips instead of one (ADR 0005)
- OCR requires the Tesseract and Poppler system binaries (not pip packages) — a fresh
  clone without them still works, just degrades gracefully to cataloging scanned
  PDFs/images instead of indexing them (see [ADR 0004](docs/decisions/0004-phase4-multimodal-processing.md)
  for install instructions; Docker and CI install them automatically)
- `RETRIEVAL_MODE=dense` is still the default — hybrid is opt-in via config, not
  automatic, so Phase 1–5's baseline stays exactly reproducible without an env change
- Reranking (`RERANKER_ENABLED`, opt-in, default off) is implemented and tested, but
  measured to *not* help on this project's small seed set (§8b) — left off by default
  because the measurement says so, not because it's unfinished
- Conversation history is now persisted to the database (`conversations`/`messages`
  tables, Phase 12) — replaces Phase 8's process-local in-memory store (ADR 0008,
  ADR 0012). No endpoint reads a conversation's transcript back out yet; the
  repository method exists (`get_all_messages`), the route just isn't wired up
- Query rewriting/decomposition/expansion require `ANTHROPIC_API_KEY` to do anything;
  without one they degrade to a no-op (tested, not a silent failure) — no fabricated
  before/after quality number exists for this phase because producing one honestly
  needs a real LLM call this dev environment doesn't have configured (ADR 0008)
- No caching, rate limiting, or auth (Phase 17/18)
- Ingestion runs in-process via `BackgroundTasks`, not a real job queue (Phase 16)
- Evaluation dataset is a small seed set, not yet the 100–300 target (Phase 13)
- Staleness detection (`check-staleness`) flags documents but never reindexes them
  automatically — that's a deliberate manual/scheduled step, not a gap
- Nothing has been deployed to a cloud environment

## 15. Future Work

See [Roadmap](#roadmap--phase-status) — this repo is built phase-by-phase per
`docs/architecture.md`; each phase adds a measured capability rather than restructuring
what's already working.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # optionally set ANTHROPIC_API_KEY to enable /query generation
uvicorn app.main:app --reload
```

Or with Docker (also brings up Postgres/Redis/frontend):
```bash
docker compose up --build
```

## Testing

```bash
pytest tests/ -v
```

254 tests, all passing. No external services or API keys are required — the vector
store, DB, and embedding model all run locally by default (see
[ADR 0001](docs/decisions/0001-phase1-stack-choices.md)). Generation-path and
vision-caption tests mock the LLM client. OCR-dependent tests run for real against
installed Tesseract/Poppler binaries and skip gracefully
(`@pytest.mark.skipif`) if they're absent, rather than mocking OCR entirely.

## Repository Structure

```
app/            FastAPI app: api / core / models / schemas / services / repositories
frontend/       Streamlit UI (Phase 1)
tests/          unit / integration / api / evaluation
evaluation/     datasets, benchmarks, reports
docs/           architecture, api, evaluation, deployment, ADRs
scripts/        run_eval.py, compare_chunking_strategies.py, other CLIs
docker/, Dockerfile, docker-compose.yml
.github/workflows/  CI (lint, test, docker build)
```

## Roadmap / Phase Status

| Phase | Status |
|---|---|
| 0 — Design | ✅ done |
| 1 — Basic MVP | ✅ done |
| 2 — Proper ingestion (DOCX/HTML/image cataloging, normalization, staleness) | ✅ done |
| 3 — Intelligent chunking (fixed/recursive/semantic, measured comparison) | ✅ done |
| 4 — Multimodal processing (OCR, structured tables, visual descriptions) | ✅ done |
| 5 — Multimodal retrieval (route queries to text/table/image specifically) | ✅ done |
| 6 — Hybrid search (dense + BM25 fusion) | ✅ done |
| 7 — Reranking (implemented, measured off by default — see §8b) | ✅ done |
| 8 — Query intelligence (rewriting, decomposition, classification) | ✅ done |
| 9 — Context engineering (relevance floor, diversity cap, compression) | ✅ done |
| 10 — Grounded generation (configurable thresholds, uncertainty hedging) | ✅ done |
| 11 — Citation engine (deterministic validation, on by default) | ✅ done |
| 12 — Conversational RAG (real DB-backed conversation persistence) | ✅ done |
| 13 — Evaluation framework (100–300 Qs) | seed harness in Phase 1, full dataset ⏳ next |
| 14 — Failure testing | partial (corrupted files across all formats), full adversarial suite ⏳ |
| 15 — Backend refactor | done by Phase 1's structure |
| 16 — Async job queue | ⏳ (Phase 1 uses BackgroundTasks) |
| 17 — Caching | ⏳ |
| 18 — Security | ⏳ |
| 19 — Observability | partial (latency stats), full metrics/logging ⏳ |
| 20 — Performance engineering | ⏳ |
| 21 — Dockerization | ✅ done |
| 22 — Testing | ✅ ongoing, expands every phase |
| 23 — CI/CD | ✅ test+build; deploy job added in Phase 24 |
| 24 — Cloud deployment | ⏳ |
| 25 — Load testing | ⏳ |
| 26–30 — Advanced/agentic RAG, dashboard, experiment tracking, final demo | ⏳ |
