# ADR 0005: Phase 5 Multimodal Retrieval

## Query classification: keyword-based, not an LLM call

`app/services/retrieval/query_classifier.py` decides whether a question's wording
points at text, table, or image evidence using keyword matching (`\bchart\b`,
`\btable\b`, `\bthe document says\b`, ...), not an LLM. This is a narrower, cheaper
question than what Phase 8 (query intelligence) will own — rewriting, expansion,
decomposition, and classification that genuinely needs language understanding (e.g.
resolving "the second quarter" from conversation history). Content-type routing is a
much shallower signal: "does this wording suggest table/image/text" is well served by
keyword matching today, and upgrading it to an LLM call later is a drop-in replacement
behind the same `classify_query_content_types(question: str) -> set[str]` signature —
nothing downstream needs to change.

## Filtering via multi-query-and-merge, not a richer filter language

`VectorStore.query`'s `filter` parameter only supports equality on a single field (see
`app/services/retrieval/vector_store.py` and `LocalVectorStore`'s implementation) —
neither backend needs an "in" / OR filter for anything else in this codebase, so
`DenseRetriever.retrieve_with_classification` doesn't ask for one just for this. When
a query matches more than one content type (e.g. "does the chart match the table?"),
it runs one filtered query per matched type and merges the results by score, capped at
`top_k`. This costs an extra round-trip per additional type — acceptable, since a
query matching 2+ types is the less common case, and it keeps the `VectorStore`
interface exactly as simple as Pinecone's and the local store's.

## `retrieve()` stays, `retrieve_with_classification()` is additive

`scripts/run_eval.py`, `scripts/compare_chunking_strategies.py`, and Phase 1–4 tests
all call `DenseRetriever.retrieve()` and only need a `list[RetrievedChunk]` back —
they don't care which content types the query matched. Rather than change that
signature (and every call site) `retrieve()` became a thin wrapper over the new
`retrieve_with_classification()`, which returns a `RetrievalResult` (chunks +
`matched_content_types`). `POST /query` uses the richer method so
`retrieval.matched_content_types` is visible in the API response — genuinely showing,
not just claiming, that a query got routed.

## `content_type` had to be added to vector store metadata

`Chunk.content_type` already existed on the SQL row since Phase 4, but the vector
store — the thing actually being *searched* — never received it; `VectorRecord`
metadata only carried `document_id`, `document_name`, `chunk_id`, `text`, `page`,
`section`. Without it, content-type filtering at query time would have been
impossible no matter how good the classifier was. Fixed in
`app/services/ingestion/pipeline.py`'s indexing step.

## Provenance in the generation prompt, not just the API response

`app/services/generation/prompt.py`'s citation locator now appends `(table)` /
`(image)` to a source's location when it isn't plain text — e.g.
`[2] Source: policy.docx, page 2 (table)`. This directly answers the brief's example
query pattern ("The document says X. Where is the evidence?") by making the evidence
type visible in the answer's own citations, not only in a side-channel API field.
