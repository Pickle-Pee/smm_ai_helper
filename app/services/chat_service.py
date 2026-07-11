from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.brand_profile_service import BrandProfileService
from app.services.chat_context_service import ChatContextService
from app.services.chat_image_service import ChatImageService
from app.services.chat_memory_service import ChatMemoryService
from app.services.chat_response_service import ChatResponseService
from app.services.chat_url_service import ChatUrlService
from app.services.intent_router import detect_intent
from app.services.scope_guard import scope_guard


class ChatService:
    """Coordinates the complete chat message flow."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        memory_service: ChatMemoryService | None = None,
        url_service: ChatUrlService | None = None,
        context_service: ChatContextService | None = None,
        response_service: ChatResponseService | None = None,
        image_service: ChatImageService | None = None,
        brand_profile_service: BrandProfileService | None = None,
        logger: logging.Logger | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.db_session = db_session
        self.logger = logger or logging.getLogger(__name__)
        self.chat_memory = memory_service or ChatMemoryService(db_session)
        self.chat_url_service = url_service or ChatUrlService(db_session)
        self.chat_context_service = context_service or ChatContextService(db_session)
        self.chat_response_service = response_service or ChatResponseService(self.logger)
        self.chat_image_service = image_service or ChatImageService()
        self.brand_profile_service = brand_profile_service or BrandProfileService()
        self.request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)

    async def handle(self, user_id: str, text: str) -> Dict[str, Any]:
        request_id = self.request_id_factory()

        self.logger.info(
            "chat_request",
            extra={"request_id": request_id, "user_id": user_id, "agent_type": "assistant"},
        )

        conversation = await self.chat_memory.get_or_create_conversation(user_id)
        await self.chat_memory.append_message(user_id=user_id, role="user", text=text)

        ok, blocked_payload = await scope_guard(text, use_llm_fallback=True)
        if not ok and blocked_payload:
            blocked_payload = self.chat_response_service.normalize(blocked_payload)
            await self.chat_memory.append_message(
                user_id=user_id,
                role="assistant",
                text=blocked_payload.get("reply", ""),
            )
            return {
                "reply": blocked_payload.get("reply", ""),
                "follow_up_question": blocked_payload.get("follow_up_question"),
                "actions": blocked_payload.get("actions", []),
                "debug": {
                    "intent": "other",
                    "used_url": False,
                    "scope_blocked": True,
                },
                "image": None,
            }

        last_messages = await self.chat_memory.load_recent_messages(
            user_id=user_id,
            limit=20,
        )

        url_context = await self.chat_url_service.analyze(text)
        url_data = url_context.data
        url_summaries = url_data.url_summaries if url_data else None

        context_update = await self.chat_context_service.update_context(
            conversation=conversation,
            user_message=text,
            last_messages=last_messages,
            url_summaries=url_summaries,
        )

        profile_context = await self.brand_profile_service.get_context_for_chat_user(
            self.db_session,
            user_id,
        )
        brand_context = self.brand_profile_service.merge_context(
            profile_context,
            context_update.facts_json,
        )

        assistant = await self.chat_response_service.generate(
            user_message=text,
            summary=context_update.summary,
            facts_json=brand_context,
            last_messages=last_messages[-10:],
            url_summaries=url_summaries,
        )

        if not url_context.used_url and url_context.has_url_intent:
            assistant["reply"] = assistant.get("reply") or ""

        await self.chat_memory.append_message(
            user_id=user_id,
            role="assistant",
            text=assistant.get("reply", ""),
        )

        intent = detect_intent(text)
        image_result = await self.chat_image_service.generate_if_requested(
            text=text,
            user_id=user_id,
            request_id=request_id,
            facts=brand_context,
        )

        image_payload = None
        if image_result:
            image_payload = image_result.image
            assistant["reply"] = image_result.reply
            assistant["follow_up_question"] = image_result.follow_up_question
            assistant["actions"] = image_result.actions
            await self.chat_memory.append_message(
                user_id=user_id,
                role="assistant",
                text=assistant["reply"],
            )

        return {
            "reply": assistant.get("reply", ""),
            "follow_up_question": assistant.get("follow_up_question"),
            "actions": assistant.get("actions", []),
            "debug": {
                "intent": intent,
                "used_url": url_context.used_url,
            },
            "image": image_payload,
        }
