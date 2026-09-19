# ADR 0006: Phase 6 Hybrid Search (Dense + BM25)

## BM25 backend: `rank_bm25`, local and disk-persisted, mirroring `LocalVectorStore`

The project brief names BM25 directly rather than a hosted search service, so
`app/services/retrieval/sparse_index.py`'s `BM25Index` is both the dev and the
"production" sparse backend — there's no cloud/local split to design the way
Pinecone/`LocalVectorStore` needed one. It deliberately mirrors `LocalVectorStore`'s
shape (`upsert`/`query`/`delete_by_document`/`count`, namespaced disk persistence,
equality-only metadata `filter`) so `HybridRetriever` can treat dense and sparse
retrieval symmetrically, and content-type filtering (Phase 5) works identically on
both.

The index rebuilds `BM25Okapi` from stored raw text on every upsert/delete rather than
pickling the fitted object. At this project's scale (thousands of chunks, not
millions) that's cheap, and it avoids `rank_bm25`/pickle version-compatibility
fragility across environments — a rebuilt index from text is always correct; a
pickled one silently isn't, if the library version changes.

## Relevance means real term overlap, not `score > 0`

Filtering candidates by `bm25_score > 0` looked like the obvious way to exclude
non-matches, but BM25's IDF term can go *negative* for very common words on a small
corpus (exactly this project's test/demo scale) — which would silently drop genuine
matches. `BM25Index.query()` instead checks actual token-set overlap between the query
and each document directly, and ranks the survivors by score. Caught by
`tests/unit/test_sparse_index.py` failing against a 2-3-document corpus before this
fix; worth remembering as a lesson about testing lexical scoring only against
large-enough corpora.

## RRF scores had to be rescaled — caught by a genuinely failing test, not by inspection

The raw RRF formula (`Σ 1/(k+rank)`) produces tiny scores — at the default `k=60`,
even a chunk ranked #1 by every retriever scores at most `n_retrievers/(k+1)` ≈ 0.033
for two retrievers. `generate_answer`'s abstention gate
(`GROUNDING_CONFIDENCE_THRESHOLD=0.35`) was calibrated against dense cosine
similarity, which lands in roughly [0, 1]. Left as-is, hybrid mode would have abstained
on *every* query regardless of actual relevance — not a hypothetical, a real failure
in `tests/api/test_query.py::test_query_with_hybrid_retrieval_mode` that surfaced this
during Phase 6 development. `reciprocal_rank_fusion` now divides by the theoretical
maximum (a chunk ranked #1 by every contributing retriever), which is a monotonic
rescale — it changes no ranking decision, only brings the score back into the same
(0, 1] range the confidence gate and the API's `relevance_score` field already assume.

Also caught in the same pass: `tests/conftest.py`'s `test_settings` fixture isolated
`LOCAL_VECTOR_STORE_DIR` per test but not the newly-added `LOCAL_SPARSE_INDEX_DIR` —
every test's BM25 index was silently writing into the same real
`./data/sparse_index` directory, so one test's ingested content could leak into
another's query results. Fixed alongside the RRF rescale; both were required for
hybrid mode's tests to pass for the right reasons rather than by accident.

## Fusion: RRF by default, weighted linear combination as the configurable alternative

Dense (cosine similarity, ~[0, 1]) and BM25 (unbounded, corpus-size-dependent) scores
aren't on comparable scales, so summing them directly would let whichever retriever
happens to produce larger numbers dominate regardless of actual relevance.
Reciprocal Rank Fusion (`score = Σ 1/(k + rank)`) sidesteps that by only using rank,
never the raw score — the standard, robust default for dense+sparse fusion. A
`weighted` mode (min-max normalize each retriever's scores, then a configurable linear
combination) is offered too, per the brief's "implement configurable fusion" — more
interpretable and tunable once you actually want to weight one retriever over the
other, but not the recommended default because it needs normalization to be
meaningful.

## Content-type routing applies before fusion, not after

`HybridRetriever` runs the Phase 5 classifier first, then does dense-search and
BM25-search *within* each matched content type before fusing — not "fuse everything,
then filter." A table-directed query fuses table-dense-candidates with
table-BM25-candidates; it never lets an off-type match from either retriever compete
for a fusion slot it can't win. Each content_type partition contributes disjoint chunk
IDs (a chunk has exactly one content_type), so concatenating per-type fused results
needs no further deduplication.

## Sparse index is always populated, independent of RETRIEVAL_MODE

`run_ingestion` upserts into both the vector store and the sparse index unconditionally
— never gated on `settings.retrieval_mode`. Otherwise, switching `RETRIEVAL_MODE` from
`dense` to `hybrid` would require re-ingesting every existing document before hybrid
search actually had anything to search. The dense-only default (`RETRIEVAL_MODE=dense`)
exists so Phase 1–5's baseline stays reproducible without opting in; hybrid is one
config change away, not a re-ingestion away.

## Comparison methodology differs from Phase 3's, deliberately

Phase 3 (chunking strategies) needed content-based substring matching because
different strategies draw different chunk boundaries through the same text — chunk_ids
aren't comparable across strategies. Dense vs. hybrid retrieval is a different axis:
both modes search the *same* chunks (same `CHUNKING_STRATEGY`, same chunk_ids), only
the ranking differs. So `scripts/compare_retrieval_modes.py` reuses Phase 1's exact
chunk_id-based `retrieval_metrics.aggregate_metrics` directly against
`expected_chunks` — the original ground truth is still valid here, and reusing it
(rather than building parallel substring-based metrics for no reason) keeps the
dense-vs-hybrid comparison numbers directly comparable to the Phase 1 baseline report.
