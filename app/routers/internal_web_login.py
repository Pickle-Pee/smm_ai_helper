"""Telegram-only login routes. The public edge must never route /internal."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.security import require_actor
from app.services import web_auth
from app.web_security import valid_config

router = APIRouter(prefix="/internal/identity")
_CONFIRM_LIMIT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 600) end
return count
"""


def enabled_actor(actor: int = Depends(require_actor)) -> int:
    if not (settings.WEB_API_ENABLED and settings.WEB_TELEGRAM_LOGIN_ENABLED):
        raise HTTPException(403, "feature_disabled")
    if not valid_config():
        raise HTTPException(503, "temporarily_unavailable")
    return actor


async def limit_confirm(actor: int = Depends(enabled_actor)) -> int:
    # Charge even malformed/replayed attempts before looking up any code.
    try:
        async with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2) as redis:
            count = await redis.eval(_CONFIRM_LIMIT, 1, f"brenvio:confirm:{actor}")
    except (RedisError, OSError, ValueError):
        raise HTTPException(503, "temporarily_unavailable") from None
    if count > 10:
        raise HTTPException(429, "rate_limited", headers={"Retry-After": "600"})
    return actor


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_code: str = Field(pattern=r"^[A-Za-z0-9_-]{22}$", repr=False)


@router.post("/web-login-link")
async def issue(response: Response, actor: int = Depends(enabled_actor), db: AsyncSession = Depends(get_session)):
    try:
        async with db.begin():
            grant = await web_auth.issue(db, actor)
    except web_auth.InvalidLogin:
        raise HTTPException(409, "telegram_identity_required") from None
    except web_auth.IssueLimitExceeded:
        raise HTTPException(429, "rate_limited", headers={"Retry-After": "600"}) from None
    except (SQLAlchemyError, OSError):
        raise HTTPException(503, "temporarily_unavailable") from None
    response.headers["Cache-Control"] = "private, no-store"
    return {"url": f"{settings.WEB_APP_ORIGIN}/auth/telegram#t={grant.secret}", "expires_at": grant.expires_at}


@router.post("/web-login-confirm", status_code=204)
async def confirm(request: Request, actor: int = Depends(limit_confirm), db: AsyncSession = Depends(get_session)):
    # Authenticate before reading JSON. FastAPI's default 422 would echo invalid input.
    try:
        payload = Confirmation.model_validate_json(await request.body())
    except ValidationError:
        raise HTTPException(422, "invalid_request") from None
    try:
        async with db.begin():
            await web_auth.confirm(db, actor, payload.confirmation_code)
    except web_auth.InvalidLogin:
        raise HTTPException(401, "login_token_invalid") from None
    except (SQLAlchemyError, OSError):
        raise HTTPException(503, "temporarily_unavailable") from None
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})
