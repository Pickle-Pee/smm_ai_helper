from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import ChatMessageRequest, ChatMessageResponse
from app.services.chat_service import ChatService


router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/message", response_model=ChatMessageResponse)
async def chat_message(
    payload: ChatMessageRequest,
    session: AsyncSession = Depends(get_session),
):
    return await ChatService(session, logger=logger).handle(
        user_id=payload.user_id,
        text=payload.text,
    )
