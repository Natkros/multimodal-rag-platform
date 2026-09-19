<<<<<<< HEAD
# Multimodal RAG Platform

A production-grade Retrieval-Augmented Generation platform for heterogeneous enterprise
documents — built incrementally, phase by phase, with a measured baseline before every
claimed improvement. This README reflects **actual, current** repo state; see
[Roadmap](#roadmap--phase-status) for what's built vs. planned.

## 1. Project Overview

Enterprise knowledge lives in PDFs, DOCX, scanned documents, spreadsheet-style tables,
and diagrams — not just clean text. This platform ingests that heterogeneous corpus,
indexes it for both dense (embedding) and sparse (BM25) retrieval, and answers natural
-language questions with page-level citations, abstaining explicitly when it lacks
evidence rather than guessing. It is built as a real service (FastAPI + Postgres + a
pluggable vector store), not a notebook.

## 2. Architecture

See [docs/architecture.md](docs/architecture.md) for the full system, sequence,
ingestion/retrieval, and deployment diagrams (Mermaid). Summary:

```
Upload → validate/hash → extract → chunk → embed → index (vector store)
Query  → embed → retrieve → (rerank*) → build context → LLM → cite → answer
```
`*` reranking ships in Phase 7.

## 3. Features (current — Phase 1)

- Upload PDF / TXT / Markdown; idempotent via content-hash dedup (`409` on repeat upload)
- Structure-aware recursive chunking (headings/paragraphs preserved as metadata) + a
  fixed-size baseline chunker for comparison
- Configurable local embedding model (`sentence-transformers`, no API key required)
- Vector store behind an abstraction — `local` (numpy, zero-setup) or `pinecone`
- Dense retrieval → grounded generation (Anthropic Claude) → numbered citations
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
| LLM | Anthropic Claude, model configurable | strong grounded-generation instruction following |
| DB | PostgreSQL (prod) / SQLite (dev, tests) | same SQLAlchemy models, zero-setup local dev |
| Containerization | Docker / Compose | one-command local stack |
| Tests | pytest + FastAPI TestClient | fast, no external services required |

## 5. RAG Pipeline

`ingestion → chunking → embedding → retrieval → (reranking) → generation` — see
[docs/architecture.md](docs/architecture.md) §3–4 for sequence diagrams and
[docs/api.md](docs/api.md) for the exact request/response contracts.

## 6. Multimodal Pipeline

Not yet built — Phase 4 target: `text → OCR → tables → images → unified retrieval`.
Phase 1 supports text-bearing PDF/TXT/MD only; a scanned/image-only PDF will index with
zero extractable text and the document will be marked `FAILED` with a clear error,
never silently indexed empty.

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
| Dense (Phase 1) | 1.00 | 0.875 | 0.906 | 12.7 ms |
| Hybrid (Phase 6) | not yet implemented | | | |
| Hybrid + Reranker (Phase 7) | not yet implemented | | | |

Reproduce: `python scripts/run_eval.py` (full report incl. per-question rows written to
`evaluation/reports/`). Recall@5 of 1.0 on a 10-question seed set is expected and not
impressive by itself — the dataset is small and hand-authored against one corpus; it
exists to prove the harness is wired correctly end-to-end, not as a headline number.
The real signal comes from Phase 6/7's *comparative* deltas once the dataset grows
(Phase 13) and gets harder multi-document/table/image questions.

## 9. Performance

No load-test numbers exist yet (Phase 20/25). Per-request latency breakdown
(`retrieval_latency_ms`, `generation_latency_ms`, `total_latency_ms`) is already
returned by `POST /query` — see [docs/api.md](docs/api.md).

## 10. Failure Handling

Handled and tested today: corrupted/unparseable PDF, empty file, unsupported file type,
oversized upload, duplicate upload, LLM not configured (`503`, not a crash), zero
retrieval matches (explicit abstention, not a hallucinated answer). See
`tests/api/test_documents.py`, `tests/api/test_query.py`,
`tests/integration/test_ingestion_pipeline.py`. Broader adversarial testing (Phase 14)
is not yet built.

## 11. Security

Phase 1 is **local-dev security posture only**: no auth, CORS restricted to
`localhost:3000` by default, secrets via environment variables only (`.env`
git-ignored, `.env.example` has no real values), upload size/type validation enforced.
API-key/JWT auth, rate limiting, and input sanitization hardening are Phase 18.

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

- Text-only formats (PDF/TXT/MD); no DOCX/HTML/images/OCR/tables yet (Phase 2/4)
- Dense-only retrieval; no BM25, fusion, or reranking yet (Phase 6/7)
- No conversation memory — every `/query` call is stateless (Phase 12)
- No caching, rate limiting, or auth (Phase 17/18)
- Ingestion runs in-process via `BackgroundTasks`, not a real job queue (Phase 16)
- Evaluation dataset is a small seed set, not yet the 100–300 target (Phase 13)
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

No external services or API keys are required — the vector store, DB, and embedding
model all run locally by default (see [ADR 0001](docs/decisions/0001-phase1-stack-choices.md)).
Generation-path tests mock the LLM client.

## Repository Structure

```
app/            FastAPI app: api / core / models / schemas / services / repositories
frontend/       Streamlit UI (Phase 1)
tests/          unit / integration / api / evaluation
evaluation/     datasets, benchmarks, reports
docs/           architecture, api, evaluation, deployment, ADRs
scripts/        run_eval.py and other CLIs
docker/, Dockerfile, docker-compose.yml
.github/workflows/  CI (lint, test, docker build)
```

## Roadmap / Phase Status

| Phase | Status |
|---|---|
| 0 — Design | ✅ done |
| 1 — Basic MVP | ✅ done |
| 2 — Proper ingestion (DOCX/HTML, idempotency polish) | ⏳ next |
| 3 — Intelligent chunking experiments | ⏳ |
| 4 — Multimodal processing (OCR/tables/images) | ⏳ |
| 5 — Multimodal retrieval | ⏳ |
| 6 — Hybrid search (BM25 fusion) | ⏳ |
| 7 — Reranking | ⏳ |
| 8 — Query intelligence | ⏳ |
| 9 — Context engineering | ⏳ |
| 10 — Grounded generation | partially in Phase 1 (abstention + citations), formalized later |
| 11 — Citation engine (validation) | ⏳ |
| 12 — Conversational RAG | ⏳ |
| 13 — Evaluation framework (100–300 Qs) | seed harness in Phase 1, full dataset ⏳ |
| 14 — Failure testing | partial in Phase 1, full adversarial suite ⏳ |
| 15 — Backend refactor | mostly done by Phase 1's structure |
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
=======
# multimodal-rag-platform
>>>>>>> f94b846846a2abaa7da41232f1892b91fb2aa7cd
