from __future__ import annotations

from typing import Dict, List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message


class ChatMemoryService:
    """Persists and reads chat conversation memory."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def get_or_create_conversation(self, user_id: str) -> Conversation:
        conversation = await self.db_session.get(Conversation, user_id)
        if conversation:
            return conversation

        conversation = Conversation(user_id=user_id, summary="", facts_json={})
        self.db_session.add(conversation)
        await self.db_session.commit()
        return conversation

    async def append_message(self, user_id: str, role: str, text: str) -> Message:
        message = Message(user_id=user_id, role=role, text=text)
        self.db_session.add(message)
        await self.db_session.commit()
        return message

    async def load_recent_messages(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, str]]:
        messages_result = await self.db_session.execute(
            select(Message)
            .where(Message.user_id == user_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        messages = list(reversed(messages_result.scalars().all()))
        return [{"role": message.role, "text": message.text} for message in messages]
