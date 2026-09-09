"""Authenticated bot-to-backend boundary; Telegram IDs alone grant no access."""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import Task, TaskSessionRecord, User


def require_bot(request: Request) -> None:
    secret = settings.BOT_BACKEND_TOKEN
    if not secret:
        raise HTTPException(503, "Bot authentication is not configured")
    expected = f"Bearer {secret}"
    supplied = request.headers.get("authorization", "")
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Bot credentials required")


def require_actor(request: Request) -> int:
    require_bot(request)
    raw = request.headers.get("x-telegram-user-id", "")
    if len(raw) > 19 or not raw.isascii() or not raw.isdecimal() or not 0 < int(raw) < 2**63:
        raise HTTPException(401, "Valid Telegram actor required")
    request.state.telegram_id = int(raw)
    return int(raw)


async def authorize_legacy_request(
    request: Request,
    actor: int = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> None:
    """HTTP binding for legacy owner formats. New workflows authorize in their service."""
    params = request.path_params
    if "telegram_id" in params and str(params["telegram_id"]) != str(actor):
        raise HTTPException(403, "Resource belongs to another user")
    if "task_id" in params:
        try:
            if len(str(params["task_id"])) > 10:
                raise ValueError("Task ID out of range")
            task_id = int(params["task_id"])
            if not 0 < task_id < 2**31:
                raise ValueError("Task ID out of range")
        except ValueError:
            raise HTTPException(422, "Invalid task ID")
        owned = await session.scalar(
            select(Task.id).join(User, Task.user_id == User.id)
            .where(Task.id == task_id, User.telegram_id == actor)
        )
        if owned is None:
            raise HTTPException(404, "Task not found")
    if request.method != "POST":
        return
    try:
        payload = await request.json()
    except ValueError:
        return  # The endpoint's typed schema returns 422.
    if not isinstance(payload, dict):
        return
    if request.url.path == "/chat/message":
        if payload.get("user_id") != f"tg:{actor}":
            raise HTTPException(403, "Chat belongs to another user")
    elif request.url.path == "/tasks/answer":
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or len(session_id) > 64 or "\x00" in session_id:
            raise HTTPException(422, "Invalid session ID")
        owner = await session.scalar(
            select(TaskSessionRecord.user_id)
            .where(TaskSessionRecord.session_id == session_id)
        )
        if owner != str(actor):
            raise HTTPException(404, "Unknown session")
    elif request.url.path == "/tasks/start" or request.url.path.startswith("/agents/"):
        user = payload.get("user")
        if not isinstance(user, dict) or type(user.get("telegram_id")) is not int or user["telegram_id"] != actor:
            raise HTTPException(403, "Task actor mismatch")
