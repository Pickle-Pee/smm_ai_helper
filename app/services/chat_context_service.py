from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation
from app.services.facts_extractor import extract_facts
from app.services.summary_updater import update_summary


@dataclass(frozen=True)
class ChatContextUpdate:
    summary: str
    facts_json: Dict[str, Any]


class ChatContextService:
    """Updates semantic chat context: facts and conversation summary."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def update_context(
        self,
        conversation: Conversation,
        user_message: str,
        last_messages: List[Dict[str, str]],
        url_summaries: List[Dict[str, Any]] | None = None,
    ) -> ChatContextUpdate:
        facts_update = await extract_facts(
            current_facts=conversation.facts_json or {},
            last_user_message=user_message,
            url_summaries=url_summaries,
        )
        conversation.facts_json = facts_update["facts"]

        summary = await update_summary(conversation.summary or "", last_messages[-20:])
        conversation.summary = summary
        conversation.updated_at = datetime.utcnow()
        await self.db_session.commit()

        return ChatContextUpdate(
            summary=conversation.summary or "",
            facts_json=conversation.facts_json or {},
        )
