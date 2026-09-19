# ADR 0007: Phase 7 Reranking

## Model: a local cross-encoder, not an API call

`app/services/reranking/reranker.py` uses `sentence-transformers`'s `CrossEncoder`
with `cross-encoder/ms-marco-MiniLM-L-6-v2` — small (~90MB), well-established for
passage reranking, and runs locally like the embedding model already does. Consistent
with this project's running preference (embeddings, OCR, BM25 are all local/free):
reranking a candidate pool has a real cost per query, and a local model means that
cost is compute, not a per-request API bill or a new external dependency to configure
before the feature works at all.

## Sigmoid activation — the same problem Phase 6's RRF hit, solved the same way

Raw cross-encoder logits from this model are unbounded, not confined to any fixed
range. `GROUNDING_CONFIDENCE_THRESHOLD` (0.35) and the "high"/"low" confidence label
in `app/services/generation/generator.py` were calibrated against scores in roughly
[0, 1] — dense cosine similarity, and Phase 6's rescaled RRF fusion. Feeding raw logits
into that same threshold would silently break it (this is the second time this exact
category of bug has come up — see ADR 0006 for the RRF version). `CrossEncoderReranker.
rerank()` applies `torch.nn.Sigmoid()` to the model's output so reranked scores land
back in (0, 1) and stay compatible with the existing confidence gate, without adding a
second threshold just for reranked results.

## Candidate pool: retrieve wide, rerank narrow

`POST /query` retrieves `RERANK_CANDIDATE_POOL` (default 30) chunks when reranking is
enabled — not the caller's requested `top_k` — then reranks and trims to `top_k` only
after rescoring. Reranking a pool of 5 candidates that retrieval already narrowed down
can't recover a relevant chunk retrieval ranked 8th; a wider pool gives the (more
accurate, more expensive) reranker something real to choose among, matching the
brief's own example: "retrieve top 30, rerank, return top 5."

## Opt-in, layered on top of Phase 6's hybrid retrieval

`RERANKER_ENABLED=false` by default, same reasoning as `RETRIEVAL_MODE=dense` in
Phase 6: Phase 1–6's baseline stays exactly reproducible without an env change.
`scripts/compare_reranking.py` holds `RETRIEVAL_MODE=hybrid` fixed (Phase 6's
best-measured configuration) and only varies `RERANKER_ENABLED`, so any measured delta
is attributable to reranking alone — not conflated with the dense-vs-hybrid delta
Phase 6 already measured separately. Per the project rule ("do not assume reranking
improves the system; prove it experimentally"), see `docs/evaluation.md` / README §8b
for the actual before/after numbers this produced, not an assumption.

## Measured result: reranking did not help on this seed set — reported as such

`scripts/compare_reranking.py`, `RETRIEVAL_MODE=hybrid` fixed, 12-question seed set,
8-document corpus:

| Config | Recall@5 | MRR | nDCG@5 | Retrieval p50 | Rerank p50 | Total p50 |
|---|---:|---:|---:|---:|---:|---:|
| hybrid, no rerank | 1.000 | 0.875 | 0.906 | 38.6 ms | 0 ms | 38.6 ms |
| hybrid + rerank | 1.000 | 0.858 | 0.893 | 42.9 ms | 1605.1 ms | 1648.0 ms |

Reranking made ranking quality very slightly *worse* here (MRR 0.875→0.858, nDCG@5
0.906→0.893) while adding ~42x total latency. This is reported exactly as measured,
not adjusted or omitted, because the brief's own rule is "do not assume reranking
improves the system; prove it experimentally" — and on this dataset, it didn't. The
likely mechanism: `cross-encoder/ms-marco-MiniLM-L-6-v2` is trained on MS MARCO web
passage ranking, a different domain and question style than this project's small,
structured corpus (an employee handbook, a vendor policy DOCX, a research paper); the
hybrid retriever's dense+BM25 fusion was already ranking these particular 12 questions
about as well as a 5-way top-K permits, leaving reranking nothing to fix and a small
amount of domain-mismatch noise to introduce instead. This is not evidence reranking
is a bad idea in general — cross-encoder reranking is well-established for good
reason — it's evidence that *this* reranker, on *this* small dataset, isn't earning
its ~42x latency cost. A larger, harder evaluation set (Phase 13) or a
domain-fine-tuned reranker could change this conclusion; `RERANKER_ENABLED=false`
stays the default until a measurement says otherwise.

## Comparison methodology, same reasoning as Phase 6

Reranking doesn't move chunk boundaries — the same chunk_ids exist whether or not
`RERANKER_ENABLED` is set, only their final ranking/selection differs — so
`scripts/compare_reranking.py` reuses the exact chunk_id-based
`retrieval_metrics.aggregate_metrics()` against `expected_chunks`, the same ground
truth Phase 1 and Phase 6 already used, not Phase 3's substring-based content metrics
(which exist specifically for when boundaries genuinely differ, e.g. across chunking
strategies).
