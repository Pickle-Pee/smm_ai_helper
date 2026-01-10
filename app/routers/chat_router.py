from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Conversation, Message
from app.schemas import ChatMessageRequest, ChatMessageResponse
from app.services.assistant_core import generate_assistant_reply
from app.services.facts_extractor import extract_facts
from app.services.intent_router import detect_intent
from app.services.qc_shortener import qc_shorten
from app.services.response_policy import enforce_policy
from app.services.summary_updater import update_summary
from app.services.url_analyzer import UrlAnalyzer, extract_urls


router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/message", response_model=ChatMessageResponse)
async def chat_message(
    payload: ChatMessageRequest,
    session: AsyncSession = Depends(get_session),
):
    request_id = uuid.uuid4().hex
    user_id = payload.user_id

    logger.info(
        "chat_request",
        extra={"request_id": request_id, "user_id": user_id, "agent_type": "assistant"},
    )

    conversation = await session.get(Conversation, user_id)
    if not conversation:
        conversation = Conversation(user_id=user_id, summary="", facts_json={})
        session.add(conversation)
        await session.commit()

    user_message = Message(user_id=user_id, role="user", text=payload.text)
    session.add(user_message)
    await session.commit()

    messages_result = await session.execute(
        select(Message)
        .where(Message.user_id == user_id)
        .order_by(desc(Message.created_at))
        .limit(20)
    )
    messages = list(reversed(messages_result.scalars().all()))
    last_messages = [{"role": m.role, "text": m.text} for m in messages]

    url_analyzer = UrlAnalyzer(session)
    url_data = await url_analyzer.analyze(payload.text)
    used_url = url_data is not None

    facts_update = await extract_facts(
        current_facts=conversation.facts_json or {},
        last_user_message=payload.text,
        url_summary=url_data.url_summary if url_data else None,
    )
    conversation.facts_json = facts_update["facts"]

    summary = await update_summary(conversation.summary or "", last_messages[-20:])
    conversation.summary = summary
    conversation.updated_at = datetime.utcnow()
    await session.commit()

    assistant_raw = await generate_assistant_reply(
        summary=conversation.summary or "",
        facts_json=conversation.facts_json or {},
        last_messages=last_messages[-10:],
        last_user_text=payload.text,
        url_summary=url_data.url_summary if url_data else None,
    )
    assistant_raw = enforce_policy(assistant_raw)
    assistant_qc = await qc_shorten(assistant_raw)
    assistant = enforce_policy(assistant_qc)

    if not used_url and url_data is None and extract_urls(payload.text):
        assistant["reply"] = (
            "Не удалось открыть ссылку, отвечаю без её анализа.\n\n" + assistant["reply"]
        )

    assistant_message = Message(user_id=user_id, role="assistant", text=assistant["reply"])
    session.add(assistant_message)
    await session.commit()

    intent = detect_intent(payload.text)

    return {
        "reply": assistant.get("reply", ""),
        "follow_up_question": assistant.get("follow_up_question"),
        "actions": assistant.get("actions", []),
        "debug": {"intent": intent, "used_url": used_url},
    }
