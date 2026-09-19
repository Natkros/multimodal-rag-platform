# ADR 0002: Phase 2 Multi-Format Ingestion

## DOCX and HTML: normalize to the existing heading-marked text shape

Rather than teach the chunker (`app/services/chunking/chunker.py`) format-specific
structure for every input type, DOCX and HTML extractors normalize their content into
the same plain text with `#`..`######` heading markers that Markdown already produces.
`_extract_docx` maps `Heading 1`..`Heading 6` / `Title` paragraph styles to that syntax;
`_extract_html` does the same for `<h1>`..`<h6>`. The structure-aware recursive chunker
then works identically across Markdown, DOCX, and HTML with zero format-specific
branching in the chunker itself.

## DOCX/HTML tables: flattened, not structurally extracted

Phase 4 is explicitly where structured table extraction (headers/rows as data, not
text) belongs. Phase 2 flattens DOCX table rows into pipe-delimited text lines so the
content is at least searchable in the interim, rather than silently dropping it or
building a half-finished table extractor ahead of the phase that's actually scoped for
it.

## Images: cataloged, not indexed

An uploaded image gets a real `Document` row, a content hash (dedup works identically),
and real metadata (`image_width`, `image_height`, `image_format` via Pillow) — but zero
chunks and no vector-store entry. `ExtractionResult.is_visual_only=True` tells the
ingestion pipeline to skip chunking/embedding entirely rather than embedding an empty
string or fabricating placeholder text. This means an uploaded image is *not yet*
retrievable by `/query` — that's honest: OCR and visual description are Phase 4/5 scope,
and claiming otherwise here would be exactly the kind of unmeasured, unearned capability
claim the project's engineering rules rule out.

## REINDEX_REQUIRED: given a real trigger

Phase 1 defined the `REINDEX_REQUIRED` status but nothing ever set it.
`app/services/ingestion/staleness.py` gives it a concrete meaning: every successful
index run stamps the document's `metadata_json` with the chunking strategy and
embedding model used (`indexed_with_chunking_strategy`, `indexed_with_embedding_model`).
`POST /documents/check-staleness` compares that fingerprint against current server
config and flags mismatches as `REINDEX_REQUIRED` — a resting state distinct from
`PROCESSING` (an active reindex). Nothing reindexes automatically; flagging is a
deliberate, inspectable step, and an operator (or a future scheduled job) decides when
to act on it.

## Normalization is a separate, narrow step

`app/utils/text_normalize.py` runs after extraction and before chunking for all
text-bearing formats: Unicode NFC normalization, CRLF→LF, and collapsing runs of blank
lines. It does not rewrite words, fix spelling, or strip content — anything a citation
later points to must still match what a human sees in the source document.
