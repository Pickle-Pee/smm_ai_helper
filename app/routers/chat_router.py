from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.security import authorize_legacy_request
from app.schemas import ChatMessageRequest, ChatMessageResponse
from app.services.chat_service import ChatService
from app.services.chat_memory_service import ChatMemoryService
from app.services.chat_execution_service import ChatExecutionService
from app.marketing_copilot.api_errors import CopilotAPIError
from app.routers.copilot import CopilotRoute


router = APIRouter(prefix="/chat", tags=["chat"], route_class=CopilotRoute, dependencies=[Depends(authorize_legacy_request)])
logger = logging.getLogger(__name__)


@router.post("/message", response_model=ChatMessageResponse)
async def chat_message(
    payload: ChatMessageRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        scope = await ChatMemoryService(session).resolve_scope(payload.user_id, payload.context_version)
        # Scope lookup is a short read, never a transaction around external work.
        await session.rollback()
        async def operation():
            return await ChatService(session, logger=logger).handle(
                user_id=payload.user_id, text=payload.text, memory_user_id=scope)
        if payload.request_key is not None:
            return await ChatExecutionService().execute(int(payload.user_id[3:]),
                payload.request_key, payload, scope, operation)
        # Backward-compatible clients may omit identity; the Telegram adapter
        # always supplies one for new updates and inline actions.
        await ChatExecutionService().admit_unkeyed(int(payload.user_id[3:]), scope)
        return await operation()
    except CopilotAPIError as exc:
        raise HTTPException(exc.status, exc.code) from None
