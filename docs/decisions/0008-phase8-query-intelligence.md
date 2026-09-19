# ADR 0008: Phase 8 Query Intelligence

## Scope: classification is deterministic, rewriting/decomposition/expansion are LLM calls

`app/services/query_intelligence/analysis.py` (ambiguous/short/multi-part/follow-up
detection, year/quarter extraction) is pure Python — cheap structural signals, same
reasoning as Phase 5's `query_classifier.py`: deciding *whether* a question needs
LLM-backed rewriting doesn't itself need language understanding. Rewriting
(`rewriter.py`), decomposition (`decomposition.py`), and expansion (`expansion.py`)
genuinely need an LLM — resolving "what about the second quarter?" against
conversation history, or splitting a comparison question into independently
retrievable sub-questions, is real language understanding, not pattern matching.

## Conversation history: in-memory, not Phase 12's persistence layer

`app/services/query_intelligence/conversation_store.py` is a process-local,
in-memory `dict[conversation_id, list[(question, answer)]]`, capped at
`CONVERSATION_HISTORY_MAX_TURNS` (default 5) — not a database table. The brief's
Phase 12 ("Conversational RAG") owns real persistence: `conversation_id`, `user_id`,
per-message timestamps, retrieved sources, presumably queryable and durable across
restarts. Building that schema now, when Phase 8 only needs "the last few
question/answer pairs to resolve a pronoun," would be exactly the kind of premature
abstraction this project's engineering rules warn against — three genuinely similar
lines beat a speculative table design built ahead of the phase that actually needs it.
**Known limitation, stated plainly**: history is lost on process restart, and there is
no cross-process sharing (irrelevant today since the API runs as one process; would
matter once Phase 16 adds a worker pool or the API scales to multiple replicas).
Phase 12 replaces this module's storage, not its rewriting logic — `rewriter.py`
doesn't care where `history: list[tuple[str, str]]` came from.

## Every LLM-backed step fails soft, independently

Same pattern as `vision_describer.py` (Phase 4) and `AnthropicLLMClient` generally: an
unconfigured or failing LLM makes `rewrite_follow_up` return the original question,
`decompose_query` return `[]`, and `expand_query` return `[]` — never an exception
that reaches the API layer. `app/services/query_intelligence/pipeline.py` wraps each
`get_llm_client()` call individually and treats `LLMNotConfiguredError` as "skip this
step," not "fail the request." The route's own generation call is the one place an
unconfigured LLM still surfaces as a real error (`503`), because generation has no
fallback — an answer that wasn't generated isn't a degraded answer, it's no answer.

## Decomposition and expansion are mutually exclusive, not combined

A multi-part question gets decomposed into sub-questions instead of expanded — running
both would multiply retrieval operations (each sub-question is itself a retrieval
call) without a clear benefit, and decomposition already produces the "multiple
targeted queries" effect expansion is trying to achieve. `pipeline.py` only attempts
expansion when decomposition produced nothing (`if settings.query_expansion_enabled
and not sub_questions`).

## Document-mention detection: substring overlap, not an LLM call

`document_matcher.py` decides whether a question names a specific indexed document
("in the vendor security policy...") by comparing significant words in the question
against each document's filename — deterministic, same reasoning as
`query_classifier.py`. Requires at least 2 overlapping significant words (1 for a
short filename) to avoid a single generic word like "revenue" spuriously matching
every document that happens to discuss revenue. Only applied when the caller didn't
already pass explicit `document_ids` — an explicit filter always wins over an
inferred one.

## What is and isn't measured here — no fabricated before/after number

Phases 3, 6, and 7 each shipped a real measured comparison because their mechanisms
are fully local and deterministic (or, for the reranker, a local model) — dense vs.
hybrid, fixed vs. recursive vs. semantic chunking, and reranked vs. not can all be run
end-to-end offline. Phase 8's actual value — resolving a follow-up correctly,
decomposing a comparison question usefully — depends on a real LLM call
(`ANTHROPIC_API_KEY`), which is not configured in this development environment. Every
rewrite/decompose/expand code path is tested against a scripted fake LLM client that
proves the *orchestration* is correct (the right prompt gets built, the right fallback
happens on failure, sub-questions get tracked as separate retrieval operations, a
follow-up's rewritten form actually reaches retrieval — see
`tests/api/test_query.py::test_query_follow_up_resolved_across_two_turns` and
`::test_query_decomposition_tracks_each_retrieval_operation`, both exercising the real
`/query` endpoint end-to-end with a fake client standing in for Claude). What is *not*
claimed is a measured quality delta from real LLM-generated rewrites/decompositions on
the evaluation dataset — producing that would require a real API key and real judgment
of whether a given rewrite/decomposition actually improved retrieval, which this
project's rules ("never fabricate evaluation results") do not allow substituting with
a guess. If a key is configured, `scripts/compare_reranking.py`'s isolation pattern
would generalize directly to a `compare_query_intelligence.py` — deliberately not
built yet, since a script that can't produce a real number isn't worth shipping ahead
of the measurement it would produce.
