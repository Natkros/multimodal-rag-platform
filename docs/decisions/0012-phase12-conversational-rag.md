# ADR 0012: Phase 12 Conversational RAG (Real Persistence)

## Scope: replace Phase 8's in-memory store, not its rewriting logic

As flagged in ADR 0008, `app/services/query_intelligence/conversation_store.py` was
always a placeholder — a process-local `dict[conversation_id, list[(question,
answer)]]` that loses history on restart and can't be shared across worker
processes. Phase 12 replaces it with `Conversation`/`Message` SQLAlchemy models
(`app/models/db.py`) and `app/repositories/conversation_repository.py`, backed by the
same Postgres/SQLite database every other repository already uses. Nothing about
*how* a follow-up gets rewritten, a question gets decomposed, or a question gets
expanded changed — `app/services/query_intelligence/pipeline.py`'s `process_query()`
now takes `history: list[tuple[str, str]]` as a parameter instead of fetching it
itself, and every LLM-backed step (`rewriter.py`, `decomposition.py`, `expansion.py`)
is unaware anything moved.

## Persistence is independent of query intelligence being enabled

`app/api/routes/query.py` records a conversation's turns whenever the caller supplies
a `conversation_id`, regardless of `QUERY_INTELLIGENCE_ENABLED`. These are two
separable concerns: durably storing what was asked and answered (useful for audit,
a future transcript endpoint, or simply resuming a conversation) versus using that
history to rewrite an ambiguous follow-up (Phase 8's feature, which stays
opt-in via `QUERY_INTELLIGENCE_ENABLED` and `QUERY_REWRITE_ENABLED`). Fetching
`get_recent_turns()` for the rewriter is gated on query intelligence being enabled —
no reason to pay a DB round-trip for history nobody will read — but
`get_or_create()`/`add_message()` are not.

## Schema: two tables, no migration tooling

```
conversations(conversation_id PK, user_id NULL, created_at)
messages(message_id PK, conversation_id FK CASCADE, role, content,
         retrieved_source_chunk_ids JSON, created_at)
```

`role` is `"user"` or `"assistant"` as a plain string, not an enum — same reasoning as
`Document.processing_status`: it's a fixed small set of values, not something that
needs a database-level constraint at this project's scale. `retrieved_source_chunk_ids`
stores the chunk IDs an assistant answer cited (`result.sources`), giving each stored
answer real provenance without duplicating chunk content. Tables are created via the
same `Base.metadata.create_all()` every other model already goes through in
`init_db()` — this project has no migration framework (see ADR 0001), and adding one
for two new tables would be solving a problem the project doesn't have yet.

## `get_recent_turns` pairs messages by adjacency, not by a stored turn ID

Turns aren't stored as a first-class row; `ConversationRepository.get_recent_turns()`
reconstructs them by walking messages in timestamp order and pairing each user message
with the assistant message that immediately follows it. A trailing unanswered user
message (the request currently in flight, or a truncated conversation) is dropped
rather than paired with `None` — `rewriter.py` expects `list[tuple[str, str]]` of
complete turns, and a half-turn can't be resolved against. This mirrors exactly what
Phase 8's in-memory `append_turn()` did (it only ever appended complete
question/answer pairs), so behavior for the rewriter is unchanged — only where the
pairs come from is different. Verified in
`tests/unit/test_conversation_repository.py::test_get_recent_turns_ignores_dangling_unanswered_question`.

## What wasn't built: a `GET /conversations/{id}` endpoint

Storing full conversation history unlocks an obvious follow-up feature (a transcript
endpoint, a "resume this conversation" UI), but nothing in the 30-phase brief asks for
one yet and no consumer exists to test it against. `ConversationRepository.get_all_messages()`
already provides everything such an endpoint would need — adding the route itself is
a small, low-risk addition deferred until there's an actual reason to expose it,
consistent with this project's rule against building ahead of what's needed.

## Testing

`tests/unit/test_conversation_repository.py` covers the repository directly:
idempotent `get_or_create`, message persistence with source chunk IDs, turn-pairing
(including the dangling-question case and a `max_turns` cap), and an empty result for
an unknown conversation. `tests/unit/test_query_intelligence_pipeline.py` was updated
to pass `history` as a plain list of tuples instead of going through the deleted
`conversation_store` module — the pipeline's own tests never needed a database in the
first place, since `process_query()` no longer touches persistence at all. The
existing end-to-end tests in `tests/api/test_query.py`
(`test_query_follow_up_resolved_across_two_turns` and friends) continue to exercise
the real `/query` route, which now reads and writes through the database instead of
the in-memory dict — no test changes were needed there beyond what conftest.py's
`test_settings` fixture already provides (a fresh SQLite file per test).
