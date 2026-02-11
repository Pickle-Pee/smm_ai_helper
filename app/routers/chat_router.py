from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Conversation, Message
from app.schemas import ChatMessageRequest, ChatMessageResponse
from app.services.assistant_core import generate_assistant_reply
from app.services.assistant_normalizer import normalize_assistant_payload
from app.services.facts_extractor import extract_facts
from app.services.image_orchestrator import ImageOrchestrator
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
    image_orchestrator = ImageOrchestrator()
    request_id = uuid.uuid4().hex
    user_id = payload.user_id

    logger.info(
        "chat_request",
        extra={"request_id": request_id, "user_id": user_id, "agent_type": "assistant"},
    )

    # upsert conversation
    conversation = await session.get(Conversation, user_id)
    if not conversation:
        conversation = Conversation(user_id=user_id, summary="", facts_json={})
        session.add(conversation)
        await session.commit()

    # persist user msg
    user_message = Message(user_id=user_id, role="user", text=payload.text)
    session.add(user_message)
    await session.commit()

    # ---------------------------
    # 1) Scope guard (маркетинг only)
    # ---------------------------
    ok, blocked_payload = await scope_guard(payload.text, use_llm_fallback=True)
    if not ok and blocked_payload:
        blocked_payload = enforce_policy(blocked_payload)
        blocked_payload = normalize_assistant_payload(blocked_payload)

        assistant_message = Message(
            user_id=user_id, role="assistant", text=blocked_payload.get("reply", "")
        )
        session.add(assistant_message)
        await session.commit()

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
    messages_result = await session.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(desc(Message.created_at))
        .limit(20)
    )
    messages = list(reversed(messages_result.scalars().all()))
    last_messages = [{"role": m.role, "text": m.text} for m in messages]

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
    assistant_message = Message(user_id=user_id, role="assistant", text=assistant.get("reply", ""))
    session.add(assistant_message)
    await session.commit()

    intent = detect_intent(payload.text)

    # ---------------------------
    # 7) Image intent (если пользователь просит картинку)
    # ---------------------------
    image_payload = None

    txt = (payload.text or "").lower()
    wants_image = any(
        k in txt
        for k in [
            "сгенерируй картин",
            "сделай картин",
            "картинк",
            "баннер",
            "креатив",
            "обложк",
            "визуал",
            "изображен",
        ]
    )

    if wants_image:
        platform = "vk" if ("вк" in txt or "vk" in txt) else "auto"
        use_case = "ad_post" if ("реклам" in txt or "промо" in txt) else "post"

        facts = conversation.facts_json or {}
        brand: Dict[str, Any] = {
            "brand_name": facts.get("brand_name"),
            "product_description": facts.get("product_description"),
            "audience": facts.get("audience"),
            "tone": facts.get("tone"),
            "goals": facts.get("goals"),
            "channels": facts.get("channels"),
        }

        # Генерация изображения (лучше message=payload.text — ок, но можно улучшить позже)
        result = await image_orchestrator.generate(
            platform=platform,
            use_case=use_case,
            message=payload.text,
            brand=brand,
            overlay=None,
            variants=1,
            user_id=user_id,
            request_id=request_id,
        )

        image_payload = {
            "status": "done",
            "mode": result["mode"],
            "preset_id": result["preset_id"],
            "size": result["size"],
            "images": [{"url": f"/images/{image_id}.png"} for image_id in result["image_ids"]],
        }

        # UX: переписываем reply, чтобы не было “инструкций”, а было подтверждение
        assistant["reply"] = (
            "Сгенерировал креатив ✅\n\n"
            "Хочешь ещё 2 варианта? Могу сделать: минимализм / яркий-игровой / премиум."
        )
        assistant["follow_up_question"] = "Какой стиль выбрать: минимализм / яркий / премиум?"
        assistant["actions"] = [
            {"type": "suggestion", "text": "Сделать ещё 2 варианта (разные стили)"},
            {"type": "suggestion", "text": "Добавить текст на баннер (заголовок + CTA)"},
        ]

        # (опционально) можно сохранить ещё одно assistant message уже с новым reply
        # чтобы история совпадала с тем, что увидел пользователь:
        assistant_message2 = Message(user_id=user_id, role="assistant", text=assistant["reply"])
        session.add(assistant_message2)
        await session.commit()

    return {
        "reply": assistant.get("reply", ""),
        "follow_up_question": assistant.get("follow_up_question"),
        "actions": assistant.get("actions", []),
        "debug": {"intent": intent, "used_url": used_url},
        "image": image_payload,
    }
