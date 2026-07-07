from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import ChatMessageRequest, ChatMessageResponse
from app.services.assistant_core import generate_assistant_reply
from app.services.assistant_normalizer import normalize_assistant_payload
from app.services.chat_image_service import ChatImageService
from app.services.chat_memory_service import ChatMemoryService
from app.services.facts_extractor import extract_facts
from app.services.intent_router import detect_intent
from app.services.qc_shortener import qc_shorten
from app.services.response_policy import enforce_policy
from app.services.scope_guard import scope_guard  # <-- ДОБАВИЛИ
from app.services.summary_updater import update_summary
from app.services.url_analyzer import UrlAnalyzer, extract_urls


router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/message", response_model=ChatMessageResponse)
async def chat_message(
    payload: ChatMessageRequest,
    session: AsyncSession = Depends(get_session),
):
    chat_memory = ChatMemoryService(session)
    chat_image_service = ChatImageService()
    request_id = uuid.uuid4().hex
    user_id = payload.user_id

    logger.info(
        "chat_request",
        extra={"request_id": request_id, "user_id": user_id, "agent_type": "assistant"},
    )

    conversation = await chat_memory.get_or_create_conversation(user_id)
    await chat_memory.append_message(user_id=user_id, role="user", text=payload.text)

    # ---------------------------
    # 1) Scope guard (маркетинг only)
    # ---------------------------
    ok, blocked_payload = await scope_guard(payload.text, use_llm_fallback=True)
    if not ok and blocked_payload:
        blocked_payload = enforce_policy(blocked_payload)
        blocked_payload = normalize_assistant_payload(blocked_payload)

        await chat_memory.append_message(
            user_id=user_id,
            role="assistant",
            text=blocked_payload.get("reply", ""),
        )

        return {
            "reply": blocked_payload.get("reply", ""),
            "follow_up_question": blocked_payload.get("follow_up_question"),
            "actions": blocked_payload.get("actions", []),
            "debug": {"intent": "other", "used_url": False, "scope_blocked": True},
            "image": None,
        }

    # ---------------------------
    # 2) Load recent messages
    # ---------------------------
    last_messages = await chat_memory.load_recent_messages(user_id=user_id, limit=20)

    # ---------------------------
    # 3) URL analyze (если есть ссылки)
    # ---------------------------
    url_analyzer = UrlAnalyzer(session)
    url_data = await url_analyzer.analyze(payload.text)
    used_url = url_data is not None

    # ---------------------------
    # 4) Facts update
    # ---------------------------
    facts_update = await extract_facts(
        current_facts=conversation.facts_json or {},
        last_user_message=payload.text,
        url_summaries=url_data.url_summaries if url_data else None,
    )
    conversation.facts_json = facts_update["facts"]

    # ---------------------------
    # 5) Summary update
    # ---------------------------
    summary = await update_summary(conversation.summary or "", last_messages[-20:])
    conversation.summary = summary
    conversation.updated_at = datetime.utcnow()
    await session.commit()

    # ---------------------------
    # 6) Assistant core (LLM)
    # ---------------------------
    assistant_raw = await generate_assistant_reply(
        user_message=payload.text,
        summary=conversation.summary or "",
        facts_json=conversation.facts_json or {},
        last_messages=last_messages[-10:],
        url_summaries=url_data.url_summaries if url_data else None,
    )
    assistant_raw = enforce_policy(assistant_raw)
    try:
        assistant_qc = await qc_shorten(assistant_raw)
    except Exception:
        logger.exception("qc_shorten failed unexpectedly")
        assistant_qc = assistant_raw
    assistant = enforce_policy(assistant_qc)
    assistant = normalize_assistant_payload(assistant)

    if not used_url and url_data is None and extract_urls(payload.text):
        assistant["reply"] = (assistant.get("reply") or "")

    # persist assistant msg (по умолчанию — текст)
    await chat_memory.append_message(user_id=user_id, role="assistant", text=assistant.get("reply", ""))

    intent = detect_intent(payload.text)

    # ---------------------------
    # 7) Image intent (если пользователь просит картинку)
    # ---------------------------
    image_payload = None
    image_result = await chat_image_service.generate_if_requested(
        text=payload.text,
        user_id=user_id,
        request_id=request_id,
        facts=conversation.facts_json or {},
    )

    if image_result:
        image_payload = image_result.image
        assistant["reply"] = image_result.reply
        assistant["follow_up_question"] = image_result.follow_up_question
        assistant["actions"] = image_result.actions

        # (опционально) можно сохранить ещё одно assistant message уже с новым reply
        # чтобы история совпадала с тем, что увидел пользователь:
        await chat_memory.append_message(user_id=user_id, role="assistant", text=assistant["reply"])

    return {
        "reply": assistant.get("reply", ""),
        "follow_up_question": assistant.get("follow_up_question"),
        "actions": assistant.get("actions", []),
        "debug": {"intent": intent, "used_url": used_url},
        "image": image_payload,
    }
