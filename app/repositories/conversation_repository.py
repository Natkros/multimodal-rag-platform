from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import Conversation, Message


class ConversationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, conversation_id: str, user_id: str | None = None) -> Conversation:
        conversation = self.db.get(Conversation, conversation_id)
        if conversation is None:
            conversation = Conversation(conversation_id=conversation_id, user_id=user_id)
            self.db.add(conversation)
            self.db.commit()
        return conversation

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        retrieved_source_chunk_ids: list[str] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            retrieved_source_chunk_ids=retrieved_source_chunk_ids or [],
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_recent_turns(self, conversation_id: str, max_turns: int) -> list[tuple[str, str]]:
        """Returns up to the last `max_turns` (question, answer) pairs, oldest first —
        the shape app/services/query_intelligence/rewriter.py expects."""
        messages = list(
            self.db.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
            ).scalars()
        )
        turns: list[tuple[str, str]] = []
        pending_question: str | None = None
        for message in messages:
            if message.role == "user":
                pending_question = message.content
            elif message.role == "assistant" and pending_question is not None:
                turns.append((pending_question, message.content))
                pending_question = None
        return turns[-max_turns:]

    def get_all_messages(self, conversation_id: str) -> list[Message]:
        return list(
            self.db.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
            ).scalars()
        )
