"""In-memory, process-local conversation history — just enough to support Phase 8's
query rewriting (resolving "what about the second quarter?" against prior turns).

Deliberately not a database table. Phase 12 ("Conversational RAG") owns real
persistence (conversation_id, user_id, per-message timestamps, retrieved sources) —
building that schema now, before Phase 8 even needs more than "the last few
question/answer pairs," would be exactly the kind of premature abstraction this
project's engineering rules warn against. History here is lost on process restart;
that's a known, documented limitation (see ADR 0008), not an oversight.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_history: dict[str, list[tuple[str, str]]] = {}


def get_history(conversation_id: str | None, max_turns: int) -> list[tuple[str, str]]:
    if not conversation_id:
        return []
    with _lock:
        return list(_history.get(conversation_id, []))[-max_turns:]


def append_turn(conversation_id: str | None, question: str, answer: str, max_turns: int) -> None:
    if not conversation_id:
        return
    with _lock:
        turns = _history.setdefault(conversation_id, [])
        turns.append((question, answer))
        if len(turns) > max_turns:
            del turns[:-max_turns]


def reset_all() -> None:
    """Test-only: clears all conversation state. Called from tests/conftest.py's
    per-test teardown so conversation history never leaks between tests."""
    with _lock:
        _history.clear()
