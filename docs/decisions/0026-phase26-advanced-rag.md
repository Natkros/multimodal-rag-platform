# ADR 0026: Phase 26 Advanced RAG Techniques

## Choosing MMR over HyDE/Self-RAG/CRAG — measurability, not novelty

Phases 3/5/6/7/8/9 already cover chunking strategy, multimodal routing, hybrid
fusion, cross-encoder reranking, query rewriting/decomposition/expansion, and
context engineering. Of the remaining well-known "advanced RAG" techniques, the
most commonly cited (HyDE — embed an LLM-generated hypothetical answer instead of
the raw query; Self-RAG/CRAG — an LLM judges retrieved-chunk relevance and can
trigger a re-retrieval) all fundamentally require a configured LLM to do anything
at all. This dev environment has no `ANTHROPIC_API_KEY` — the same constraint that
already shaped ADR 0008 and ADR 0013's scope. Building HyDE/CRAG here would mean
either shipping an untested mechanism (only provably correct via a scripted fake
LLM client, never given a real quality measurement) or fabricating a before/after
number, both of which this project's rules forbid. **Maximal Marginal Relevance
(MMR)** was chosen instead because it's a real, standard advanced-RAG technique
that is entirely local and deterministic (embedding-similarity based, no LLM call)
— genuinely measurable against the existing 57-question eval harness the same way
Phase 6/7 measured hybrid search and reranking.

## What MMR does here, and how it composes with reranking

`app/services/retrieval/mmr.py::select_with_mmr()` greedily selects `top_k`
results from a candidate pool, at each step picking the candidate maximizing
`lambda * relevance - (1 - lambda) * max_similarity_to_already_selected` — trading
off a candidate's own retrieval/rerank score against how similar it is to what's
already been picked, using cosine similarity between each candidate's own text
embedding (computed on the fly via `embedder.embed_documents()`, not requiring any
change to the `VectorStore` protocol, which doesn't return raw vectors — see
`app/services/retrieval/vector_store.py`). `MMR_ENABLED=false` by default,
`MMR_LAMBDA=0.5` splits relevance and diversity evenly.

Composing with Phase 7's reranker required one real change:
`app/services/query_service.py` now reranks the *whole* candidate pool
(`pool_k`, not `request.top_k`) when MMR will also run, since MMR needs more
candidates than `top_k` to actually choose diversity from — reranking straight
down to `top_k` first would leave MMR nothing to select among. Verified by
`tests/api/test_query.py::test_query_with_mmr_and_reranking_both_enabled`.

## Measured result: MMR is a real, honest negative on this eval set — same category of finding as Phase 7's reranker

`scripts/compare_mmr.py` holds `RETRIEVAL_MODE=dense` fixed and only varies
`MMR_ENABLED`, over the full 57-question dataset (full report:
`evaluation/reports/mmr_comparison_20260920_032310.json`):

| Config | Recall@5 | MRR | nDCG@5 | Avg intra-result similarity | Latency p50 |
|---|---:|---:|---:|---:|---:|
| dense, no MMR | 0.900 | 0.751 | 0.789 | 0.3331 | 132.5 ms |
| dense + MMR (λ=0.5) | 0.660 | 0.654 | 0.645 | 0.1192 | 875.8 ms |

**MMR does exactly what it's designed to do — average intra-result similarity
drops 64% (0.333 → 0.119), genuinely more diverse result sets — and that costs
real ranking quality on this corpus**: Recall@5 drops from 0.900 to 0.660, MRR
from 0.751 to 0.654, nDCG@5 from 0.789 to 0.645, at ~6.6x latency (the extra cost
of embedding the full candidate pool for pairwise similarity, on top of whatever
retrieval already did). The most likely explanation: this project's 57-question
eval set is predominantly single-answer factual QA (Phase 13's dataset — "what is
the reimbursement window," "what BLEU score did the paper report") where there is
one genuinely correct chunk, not several equally-valid but differently-phrased
good answers. MMR is built for exactly the opposite case — exploratory or
open-ended queries where the "right" answer benefits from covering several
distinct angles — and actively penalizes picking the single correct chunk twice in
a row if a second (wrong, but sufficiently different) chunk scores only slightly
lower. Reported exactly as measured, the same discipline Phase 7 applied to
reranking: **`MMR_ENABLED=false` stays the default**, not because MMR is a bad
technique in general, but because it measurably doesn't help *this* dataset's
query shape, and "prove it experimentally" cuts both ways — a negative result is
as valid an outcome as a positive one.

## Testing

`tests/unit/test_mmr.py`: `lambda_param=1.0` degenerates to plain relevance
ranking (verified against a hand-constructed case where ignoring diversity
would obviously differ); a near-duplicate candidate loses to a lower-scored but
distinct one when diversity is weighted in; empty input, `top_k` smaller than the
pool, and `average_pairwise_similarity`'s edge cases (0/1 vectors, identical
vectors → 1.0, orthogonal vectors → 0.0) are all covered directly, not just
exercised incidentally through an end-to-end test.
`tests/api/test_query.py` adds two end-to-end cases: MMR alone, and MMR combined
with reranking (the pool-widening interaction above).

## What Phase 26 did not do

- **HyDE, Self-RAG, CRAG** — all need a real, configured LLM to produce anything
  beyond a fake-client-verified mechanism with no honest quality number; deferred
  for the same reason ADR 0008/0013 deferred a measured query-intelligence
  before/after.
- **Multi-vector / ColBERT-style late-interaction retrieval** — a materially
  larger architecture change (different index structure entirely, not a
  post-retrieval step like MMR/reranking) with no evidence this project's small
  corpus needs the precision gain it targets; out of scope for an "advanced
  technique" pass meant to compose with, not replace, the existing retrieval
  stack.
- **Tuning `MMR_LAMBDA`** — `0.5` was measured as a representative midpoint, not
  swept across a range to find an optimal value for this dataset. Given the
  technique already measures net-negative at the balanced setting, a hyperparameter
  sweep chasing a better number would be optimizing something already shown not to
  help here, not a useful next step until the query mix actually calls for
  diversity.
