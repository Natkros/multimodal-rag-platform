from __future__ import annotations

from app.models.db import get_session_factory, init_db
from app.repositories.conversation_repository import ConversationRepository


def test_get_or_create_is_idempotent(test_settings):
    init_db()
    db = get_session_factory()()
    repo = ConversationRepository(db)

    first = repo.get_or_create("conv-1")
    second = repo.get_or_create("conv-1")

    assert first.conversation_id == second.conversation_id
    db.close()


def test_add_message_persists_role_content_and_sources(test_settings):
    init_db()
    db = get_session_factory()()
    repo = ConversationRepository(db)
    repo.get_or_create("conv-1")

    message = repo.add_message("conv-1", "assistant", "The answer.", retrieved_source_chunk_ids=["c1", "c2"])

    assert message.role == "assistant"
    assert message.content == "The answer."
    assert message.retrieved_source_chunk_ids == ["c1", "c2"]
    db.close()


def test_get_recent_turns_pairs_user_and_assistant_messages_in_order(test_settings):
    init_db()
    db = get_session_factory()()
    repo = ConversationRepository(db)
    repo.get_or_create("conv-1")

    repo.add_message("conv-1", "user", "What was Q1 revenue?")
    repo.add_message("conv-1", "assistant", "$38 million.")
    repo.add_message("conv-1", "user", "What about Q2?")
    repo.add_message("conv-1", "assistant", "$42 million.")

    turns = repo.get_recent_turns("conv-1", max_turns=5)

    assert turns == [
        ("What was Q1 revenue?", "$38 million."),
        ("What about Q2?", "$42 million."),
    ]
    db.close()


def test_get_recent_turns_respects_max_turns_limit(test_settings):
    init_db()
    db = get_session_factory()()
    repo = ConversationRepository(db)
    repo.get_or_create("conv-1")

    for i in range(4):
        repo.add_message("conv-1", "user", f"Question {i}")
        repo.add_message("conv-1", "assistant", f"Answer {i}")

    turns = repo.get_recent_turns("conv-1", max_turns=2)

    assert turns == [("Question 2", "Answer 2"), ("Question 3", "Answer 3")]
    db.close()


def test_get_recent_turns_ignores_dangling_unanswered_question(test_settings):
    init_db()
    db = get_session_factory()()
    repo = ConversationRepository(db)
    repo.get_or_create("conv-1")

    repo.add_message("conv-1", "user", "What was Q1 revenue?")
    repo.add_message("conv-1", "assistant", "$38 million.")
    repo.add_message("conv-1", "user", "What about Q2?")

    turns = repo.get_recent_turns("conv-1", max_turns=5)

    assert turns == [("What was Q1 revenue?", "$38 million.")]
    db.close()


def test_get_recent_turns_empty_for_unknown_conversation(test_settings):
    init_db()
    db = get_session_factory()()
    repo = ConversationRepository(db)

    assert repo.get_recent_turns("no-such-conv", max_turns=5) == []
    db.close()


def test_get_all_messages_returns_everything_in_order(test_settings):
    init_db()
    db = get_session_factory()()
    repo = ConversationRepository(db)
    repo.get_or_create("conv-1")

    repo.add_message("conv-1", "user", "Q1?")
    repo.add_message("conv-1", "assistant", "A1.")

    messages = repo.get_all_messages("conv-1")

    assert [m.role for m in messages] == ["user", "assistant"]
    assert [m.content for m in messages] == ["Q1?", "A1."]
    db.close()
