# ADR 0009: Phase 9 Context Engineering

## Everything new is opt-in; dedupe + token-budget packing stays the default

`app/services/generation/context_builder.py` already did dedupe-by-text and
token-budget packing since Phase 1. Phase 9 adds three more responsibilities — a
relevance floor (drop candidates scoring far below the top result), a per-document
diversity cap (stop one document from crowding out others), and deterministic
compression (truncate an oversized chunk instead of letting it consume the whole
budget) — each gated by its own setting, defaulting to off/unlimited. Same reasoning
as every opt-in feature since Phase 6: Phase 1–8's generation behavior stays exactly
reproducible unless a setting is explicitly changed.

## Compression means truncation, not summarization

"Compression" here is a hard per-chunk character cap (`CONTEXT_MAX_CHUNK_TOKENS`,
default 300), not an LLM-generated summary. An LLM-summarized chunk would cost a
model call per oversized chunk and risk dropping the exact sentence a citation needs
to point to — deterministic truncation is cheap, predictable, and preserves the
chunk's own wording (with a visible `[…truncated]` marker) rather than paraphrasing
it. If semantic compression proves worth the cost later, it's a drop-in replacement
behind the same `compression_enabled` flag.

## Source distribution is always computed, never gated

Unlike the three opt-in filters, `source_distribution` (chunks selected per document)
costs nothing to compute and changes no behavior — it's pure reporting, always present
in the response. Same reasoning `matched_content_types` (Phase 5) and
`retrieval_trace` (Phase 8) followed: measurable-by-default where there's no tradeoff
to gate behind a flag.
