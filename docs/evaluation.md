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
unanswerable}. Grows from a small seed set (Phase 1/13 bootstrap) toward the 100–300
target as later phases add multimodal and multi-document cases.

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
