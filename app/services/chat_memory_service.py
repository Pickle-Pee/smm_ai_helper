from __future__ import annotations

from typing import Dict, List

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert

from app.marketing_copilot.api_errors import CopilotAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActiveProjectBinding, Conversation, Message, User


class ChatMemoryService:
    """Persists and reads chat conversation memory."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def resolve_scope(self, user_id: str, expected_version: int | None = None) -> str:
        """Resolve authorized Telegram memory; a new-request epoch never reads legacy.

        External callers still authenticate as tg:<actor>. They cannot choose an
        arbitrary conversation key or bypass an active project through /chat.
        """
        import re
        match = re.fullmatch(r"tg:([1-9][0-9]{0,18})", user_id)
        if match is None:
            raise CopilotAPIError(404, "not_found")
        actor = int(match[1])
        binding = await self.db_session.scalar(select(ActiveProjectBinding).join(User,
            ActiveProjectBinding.owner_id == User.id).where(
            ActiveProjectBinding.actor_id == actor, ActiveProjectBinding.chat_id == actor,
            User.telegram_id == actor))
        if binding is None and expected_version is not None:
            # Updated Telegram clients start an isolated epoch even before their
            # first /new; historical tg:<actor> remains an archive.
            await self.db_session.execute(insert(User).values(telegram_id=actor)
                .on_conflict_do_nothing(index_elements=[User.telegram_id]))
            owner = await self.db_session.scalar(select(User.id).where(User.telegram_id == actor))
            await self.db_session.execute(insert(ActiveProjectBinding).values(
                actor_id=actor, chat_id=actor, owner_id=owner, version=0)
                .on_conflict_do_nothing(index_elements=[ActiveProjectBinding.actor_id, ActiveProjectBinding.chat_id]))
            binding = await self.db_session.scalar(select(ActiveProjectBinding).where(
                ActiveProjectBinding.actor_id == actor, ActiveProjectBinding.chat_id == actor))
            # Persist this small initialization independently of provider work.
            await self.db_session.commit()
        version = binding.version if binding else 0
        if expected_version is not None and version != expected_version:
            raise CopilotAPIError(409, "stale_context")
        if binding and binding.session_id is not None:
            raise CopilotAPIError(409, "stale_context")
        return f"tg:{actor}:new:{version}" if binding else user_id

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
