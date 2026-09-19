# Evaluation Strategy

## Principle

No quality claim ships without a number, and no number ships without a stated method.
Every metric below is tagged **[deterministic]**, **[LLM-as-judge]**, or **[human]**.

## Dataset

`evaluation/datasets/qa_dataset.jsonl` — versioned, one JSON object per line:

```json
{
  "id": "q001",
  "question": "What is Acme's Q2 2025 revenue?",
  "expected_documents": ["acme_employee_handbook.md"],
  "expected_chunks": ["acme_employee_handbook.md::chunk-10"],
  "reference_answer": "$42.3 million",
  "difficulty": "easy",
  "query_type": "factual"
}
```

`query_type` ∈ {factual, semantic, multi_document, comparison, table, image, ambiguous,
unanswerable, multi_part}. `multi_part` (added Phase 13) is a single question asking
two distinct, separately-gradable facts (e.g. "what's the price and the listing cap?")
— distinct from `comparison`, which asks the system to relate two facts to each other,
and from `multi_document`, which asks about facts that live in two different source
documents. Grew from 12 questions (Phase 1/8 bootstrap) to 57 (Phase 13) toward the
100–300 target — see [ADR 0013](decisions/0013-phase13-evaluation-expansion.md) for
why 57, not 100-300, is where honest expansion of this project's small sample corpus
currently lands.

## Retrieval Metrics — all **[deterministic]**, computed in `app/services/evaluation/retrieval_metrics.py`

- Recall@K — fraction of `expected_chunks` present in top-K results.
- Precision@K — fraction of top-K results that are in `expected_chunks`.
- MRR — reciprocal rank of the first relevant chunk.
- nDCG@K — rank-discounted relevance (binary relevance from `expected_chunks`).
- Hit Rate@K — fraction of queries with ≥1 relevant chunk in top-K.
- Retrieval / reranking latency (ms), measured via `time.perf_counter()` around each stage.

## Generation Metrics

- **Citation correctness [deterministic]**: for every `[n]` citation in the answer, the
  cited chunk's text must lexically/semantically support the sentence it's attached to
  (checked via NLI-style entailment against the cited chunk — see Phase 11).
- **Faithfulness [LLM-as-judge]**: judge model scores whether every claim in the answer
  is supported by the provided context, given the context + answer only (no external
  knowledge). Reported as a percentage with the judge model and prompt version recorded.
- **Answer relevance [LLM-as-judge]**: judge scores whether the answer addresses the
  question.
- **Hallucination rate [deterministic + LLM-as-judge]**: 1 − faithfulness, cross-checked
  against citation correctness.
- **Human spot-check [human]**: a small random sample is manually reviewed each phase to
  sanity-check the automated scores — logged in `evaluation/reports/`, never silently
  assumed equivalent to the automated numbers.

## Unanswerable Queries

`query_type=unanswerable` cases have `expected_chunks: []` by design — there is no
ground truth to recall. `aggregate_metrics()` excludes them from Recall/Precision/
nDCG/MRR (which would otherwise incorrectly read an empty ground-truth set as "0
recall") and reports `n_answerable_queries` / `n_unanswerable_queries` separately.
Whether the system correctly *abstains* on these is a generation-quality question
(Phase 10), not a retrieval-recall question — tracked separately once the citation/
abstention checker (Phase 11) lands.

## Comparison Protocol

Every retrieval/generation change is run against the full dataset before and after,
producing a row in a comparison table (`evaluation/reports/<phase>_<date>.md`):

| System | Recall@5 | MRR | nDCG@5 | Latency p50 | Latency p95 |
|---|---:|---:|---:|---:|---:|

Baselines are never deleted — Phase 1 dense-only retrieval stays runnable via
`VECTOR_STORE`/`RETRIEVAL_MODE` config so later phases can regenerate the comparison.

## What Phase 1 Ships

A `scripts/run_eval.py` CLI that loads `qa_dataset.jsonl`, runs retrieval-only metrics
(no reranker/hybrid yet — those are Phase 6/7), and writes a report. This establishes
the harness and the baseline number, not a finished evaluation suite.

## Phase 3: Chunking Strategy Comparison

Exact chunk_id matching (the retrieval-metrics approach above) only works when the
ground truth and the system under test share one chunking strategy — which stops
being true the moment you compare strategies against each other, since each one draws
different boundaries through the same source text. `evaluation/datasets/qa_dataset.jsonl`
therefore also carries `expected_answer_substrings` per question, and
`app/services/evaluation/content_metrics.py` judges relevance by whether a retrieved
chunk's *text* contains one of those substrings — true regardless of where any given
strategy split the document. Recall@K is deliberately not computed this way (it needs
a known total-relevant count that substring matching can't establish); Hit Rate@K,
Precision@K, MRR, and nDCG@K are reported instead. Full method: see
[ADR 0003](decisions/0003-phase3-chunking-comparison.md).

`scripts/compare_chunking_strategies.py` runs `fixed`, `recursive`, and `semantic`
each against an isolated DB/vector store, over the full sample_docs corpus. Measured
result (see `evaluation/reports/chunking_strategy_comparison_*.json` for full
per-question detail):

| Strategy | HitRate@5 | Precision@5 | nDCG@5 | MRR | Latency p50 | Ingest+eval wall time |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 1.000 | 0.220 | 0.882 | 0.833 | 12.7 ms | 26.9 s |
| recursive | 1.000 | 0.220 | 0.928 | 0.900 | 13.1 ms | 39.9 s |
| semantic | 1.000 | 0.440 | 0.868 | 0.808 | 20.1 ms | 131.8 s |

Reading this honestly: `recursive` has the best ranking quality (nDCG@5, MRR) on this
seed set — structure-aware boundaries that respect the handbook's headings apparently
line up well with where the answers actually live. `semantic` doubles Precision@5
(smaller, more topically-coherent chunks mean less irrelevant text riding along with
the right answer) but costs roughly 3–5x the ingestion wall time (embedding every
sentence, not just every packed chunk) and ~50% higher query latency (smaller chunks →
more vectors to search in the same corpus). `fixed` is worst on every ranking metric,
as expected for a strategy that ignores document structure entirely. This is a
10-question seed set on one small corpus — a real finding about mechanism, not a
production-grade recommendation; Phase 13's larger dataset is what would justify
switching the default.

## Phase 6: Dense vs. Hybrid (Dense + BM25) Retrieval

Unlike Phase 3's chunking comparison, dense and hybrid retrieval search the *same*
chunks (identical `CHUNKING_STRATEGY`, identical chunk_ids) — only the ranking
differs — so this reuses Phase 1's exact chunk_id-based `aggregate_metrics()` directly
against `expected_chunks`, not the Phase 3 substring-based content metrics. Full
method: [ADR 0006](decisions/0006-phase6-hybrid-search.md).

`scripts/compare_retrieval_modes.py` runs `dense` and `hybrid` (RRF fusion, default
config) each against an isolated DB/vector-store/sparse-index, over the full
sample_docs corpus and the 12-question seed set. Measured result (see
`evaluation/reports/retrieval_mode_comparison_*.json` for full per-question detail):

| Mode | Recall@5 | Recall@10 | MRR | nDCG@5 | Latency p50 |
|---|---:|---:|---:|---:|---:|
| dense | 1.000 | 1.000 | 0.750 | 0.812 | 13.6 ms |
| hybrid | 1.000 | 1.000 | 0.875 | 0.906 | 37.9 ms |

Both modes reach perfect Recall@5 on this seed set (the corpus is small enough that
dense alone already surfaces the right chunk somewhere in the top 5), so the real
signal is in *ranking quality*: hybrid's BM25 component breaks ties dense embeddings
alone can't — exact terms, numbers, and codes that matter lexically but don't
necessarily dominate a cosine-similarity ranking — moving MRR from 0.750 to 0.875 and
nDCG@5 from 0.812 to 0.906. That comes at a real, measured cost: retrieval latency
roughly tripled (13.6ms → 37.9ms p50), from running two searches and a fusion step per
query instead of one. On this project's scale that's still fast in absolute terms;
whether the ranking-quality gain is worth 2-3x retrieval latency at production scale is
exactly the kind of tradeoff Phase 20 (performance engineering) and Phase 25 (load
testing) exist to answer with real numbers, not guessed here.

## Phase 7: Reranking — a measured negative result

Same reasoning as Phase 6 applies to methodology (reranking doesn't move chunk
boundaries, so exact chunk_id metrics against `expected_chunks` stay valid). Full
method: [ADR 0007](decisions/0007-phase7-reranking.md).

`scripts/compare_reranking.py` holds `RETRIEVAL_MODE=hybrid` fixed (Phase 6's
best-measured mode) and only varies `RERANKER_ENABLED`
(`cross-encoder/ms-marco-MiniLM-L-6-v2`, candidate pool 30, final top_k 5):

| Config | Recall@5 | MRR | nDCG@5 | Retrieval p50 | Rerank p50 | Total p50 |
|---|---:|---:|---:|---:|---:|---:|
| hybrid, no rerank | 1.000 | 0.875 | 0.906 | 38.6 ms | 0 ms | 38.6 ms |
| hybrid + rerank | 1.000 | 0.858 | 0.893 | 42.9 ms | 1605.1 ms | 1648.0 ms |

**Reranking made ranking quality very slightly worse** on this seed set (MRR
0.875→0.858, nDCG@5 0.906→0.893) while adding ~42x total latency. Reported exactly as
measured — the project rule is "do not assume reranking improves the system; prove it
experimentally," and here it genuinely didn't. Most likely explanation: the reranker
is trained on MS MARCO web passage ranking, a different domain/style than this
project's small structured corpus, and hybrid retrieval was already ranking these 12
questions about as well as a 5-way top-K permits — leaving the reranker nothing to fix
and some domain-mismatch noise to introduce. This is not a verdict on cross-encoder
reranking in general (it's well-established for good reason); it's a verdict on *this*
reranker, on *this* small dataset, at *this* latency cost. `RERANKER_ENABLED=false`
stays the default until Phase 13's larger evaluation set — or a domain-appropriate
reranker — produces a different measured result.

## Phase 13: Evaluation Dataset Expansion (12 → 57 questions)

The dataset grew from 12 to 57 hand-authored questions, all grounded in this project's
existing 8-document sample corpus — no synthetic/LLM-generated questions, and no
fabricated answers (every `expected_answer_substrings` entry was checked against the
actual extracted chunk text after re-ingesting the corpus, including the two OCR
chunks, which reveal real OCR noise: `$1,240.00` reads back as `$1.240.00`, and the
revenue chart is garbled badly enough — `saaim` for `$44.1M` — that its question
deliberately carries no `expected_answer_substrings`, only a retrieval target). Every
document in the corpus now has coverage, including the two that only had 1-2
questions before (vendor security policy, RoomWise FAQ). `expected_chunks` for the 45
new questions were derived from the actual chunk IDs a real local ingestion run
produced (`deterministic_document_id` + the default `recursive` chunker), not
estimated. Full construction method, the exact 45 new question IDs, and why 57 (not
100-300) is this round's honest stopping point: [ADR 0013](decisions/0013-phase13-evaluation-expansion.md).

Dense-only retrieval, re-measured on the full 57-question set (see
`evaluation/reports/dense_baseline_20260919_192100.json`):

| Dataset | n_queries | n_answerable | Recall@5 | Hit Rate@5 | MRR | nDCG@5 | Latency p50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 12 questions (pre-Phase 13) | 12 | 10 | 1.000 | 1.000 | 0.750 | 0.812 | 13.6 ms |
| 57 questions (Phase 13) | 57 | 50 | 0.900 | 0.920 | 0.751 | 0.789 | 13.8 ms |

Recall@5 dropping from a perfect 1.0 to 0.9 is the expected, honest effect of a larger,
harder dataset surfacing real retrieval gaps the 12-question set was too small and too
easy to expose — not a regression in the system. The multi-document and multi-part
questions (two ground-truth chunks per question, e.g. q030, q048) are the main source
of the drop: a single un-decomposed dense query doesn't always land both relevant
chunks in the top 5. This is exactly the failure mode Phase 8's query decomposition
targets — the larger dataset now makes that improvement measurable in a way the old
12-question set couldn't, though quantifying it (query-intelligence-enabled vs. not,
on this dataset) is deferred to a future `compare_query_intelligence.py`, not built
this phase for the same reason Phase 8 didn't build one: it needs a configured LLM to
produce a real number, and none is configured in this dev environment.
