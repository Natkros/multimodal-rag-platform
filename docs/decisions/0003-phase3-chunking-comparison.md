# ADR 0003: Phase 3 Chunking Strategy Comparison

## Three strategies, as required

- `fixed` — naive token-count windows, ignores structure entirely (the baseline).
- `recursive` — structure-aware: splits on markdown headings/paragraphs first, packs
  into token-budgeted windows (the Phase 1 default).
- `semantic` — embeds every sentence and starts a new chunk wherever cosine similarity
  between consecutive sentences drops below `SEMANTIC_CHUNK_SIMILARITY_THRESHOLD`
  (default 0.5), so boundaries fall where the topic actually shifts rather than where a
  heading or a token-count happens to land. See
  `app/services/chunking/semantic_chunker.py`.

## Why chunk_id-based Recall@K doesn't work for this comparison

Phase 1's evaluation harness (`scripts/run_eval.py`) matches retrieved results against
a frozen list of `expected_chunks` (exact chunk IDs), which only made sense because
Phase 1 only ever ran one chunking strategy — chunk IDs are deterministic *given* a
strategy, but two strategies split the same document at different offsets and produce
entirely different chunk IDs for the same underlying text. Reusing exact-ID Recall@K
here would always show every non-`recursive` strategy scoring near zero, which isn't a
finding about chunking quality — it's an artifact of the ground truth being pinned to
one strategy's boundaries.

`app/services/evaluation/content_metrics.py` fixes this: relevance is judged by whether
a retrieved chunk's *text* contains one of the question's
`expected_answer_substrings` (see `evaluation/datasets/qa_dataset.jsonl`), which is
true regardless of where any given strategy happened to draw its boundaries. Recall@K
itself is intentionally not computed this way — it requires knowing the total count of
relevant items in the corpus, which substring matching can't establish. Hit Rate@K,
Precision@K, MRR, and nDCG@K don't have that requirement and are reported instead.

## Isolation between strategy runs

`scripts/compare_chunking_strategies.py` gives each strategy its own SQLite DB and
local vector store directory under `data/chunking_experiments/<strategy>/`, resetting
every process-wide cache (settings, embedder, vector store, DB engine) between runs —
the same pattern `tests/conftest.py`'s `test_settings` fixture uses for test isolation.
Without this, a `chunk-3` from one strategy could silently overwrite a same-ID
`chunk-3` from another in a shared vector store.

## Results

See `evaluation/reports/chunking_strategy_comparison_*.json` for the full per-question
breakdown, and `README.md` §8 for the summary table. `semantic` embeds every sentence
in every document at ingestion time (not just once per chunk), so its ingestion wall
time is measured and reported separately from retrieval quality — a real cost, not a
detail to bury.
