# ADR 0022: Phase 22 Testing

## Measure coverage first, then decide what's worth fixing

Every phase since Phase 1 added tests alongside its own feature — 306 tests existed
before this phase started. Rather than assume that was "enough" or write more
tests speculatively, this phase ran `pytest --cov=app --cov-report=term-missing`
for the first time to get a real number: **95% line coverage** (2,272 statements,
105 missed) across `app/`. `pytest-cov` is added to `requirements.txt`.

## What the missing 5% actually is — three different categories, three different responses

**Genuinely untestable in this dev environment (disclosed, not chased)**:
- `app/services/retrieval/pinecone_vector_store.py`: **0%** coverage. Nothing in
  this project's test suite has a real Pinecone account/API key, the same
  constraint noted in ADR 0008/0013 for `ANTHROPIC_API_KEY`. `VectorStore` is a
  `Protocol` specifically so `LocalVectorStore` (fully tested) proves the
  retrieval pipeline's logic works correctly against the interface; the Pinecone
  implementation itself is a thin adapter to a third-party SDK with no local
  equivalent to test against.
- `app/services/generation/llm_client.py`: **56%** (11/25 lines uncovered) — the
  "not configured" fail-loud path is fully tested; `AnthropicLLMClient`'s actual
  API-call path is not, for the same no-API-key reason.
- `app/services/retrieval/factory.py`: **81%** — the uncovered lines are
  specifically the Pinecone branch of `get_vector_store()`.

Chasing these to 100% would mean either fabricating a fake Anthropic/Pinecone
response (testing the mock, not the real integration — worse than not testing it)
or requiring real credentials in CI, which this project doesn't have and won't
invent to inflate a coverage number.

**Real gaps, fixed this phase** (added tests, not just noted):
- `app/api/routes/documents.py` was **88%** — missing `DELETE`/`POST .../reindex`/
  `GET /jobs/{id}` 404 paths, and the best-effort vector-store-cleanup-swallows-exceptions
  branch in `delete_document` was asserted only by inspection, never by a test that
  actually made the cleanup call raise. Added
  `test_delete_nonexistent_document_404`, `test_delete_document_succeeds_even_if_vector_store_cleanup_raises`,
  `test_reindex_nonexistent_document_404`, `test_reindex_without_original_file_returns_409`,
  `test_get_job_returns_status`, `test_get_nonexistent_job_404`.
- `app/services/query_intelligence/document_matcher.py` was **92%** — the
  "question has no significant words" and "a candidate document's filename is all
  stopwords" branches were unexercised. Added
  `test_question_with_no_significant_words_returns_none` and
  `test_document_with_filename_of_only_stopwords_is_skipped`.
- `app/services/observability/logging_config.py` was **96%** — `JsonFormatter`'s
  `exc_info` handling (a log record built from a real exception) was untested.
  Added `test_json_formatter_includes_exc_info`.
- `app/services/retrieval/retriever.py` was **99%** — `CachingRetriever.retrieve()`
  (the plain `list[RetrievedChunk]` wrapper around `retrieve_with_classification()`)
  had no direct test; every existing test called the classification method
  directly. Added `test_retrieve_wrapper_returns_just_the_chunks`.

**Narrow, low-value branches, left alone**: a handful of lines in
`app/services/chunking/chunker.py` (specific loop-boundary combinations in
`fixed_chunk`, e.g. an empty page's `continue`), `app/services/ingestion/staleness.py`,
and one branch in `app/services/query_service.py` (the decomposition-vs-expansion
`elif` when a request has expansion variants but wasn't already covered by an
end-to-end decomposition test) remain uncovered. These are real but narrow edge
cases already covered *indirectly* by other tests at a different layer (e.g.
`document_matcher`'s core logic is unit-tested independent of the route), and
constructing the exact input to hit each remaining line individually would cost
more than it returns — this project's rule is "measure and report honestly," not
"chase 100% regardless of marginal value," which is itself a form of the
premature-optimization the project's engineering rules warn against elsewhere.

## Coverage number going forward

95% is the number as of this phase, not a target this project claims to maintain
automatically — no coverage gate was added to CI this phase (see ADR 0023 for
whether Phase 23 adds one). The report itself
(`pytest --cov=app --cov-report=term-missing`) is trivially reproducible by anyone
who clones the repo; nothing here is a number that can drift out of sync with
reality without the next `pytest` run immediately contradicting it.
