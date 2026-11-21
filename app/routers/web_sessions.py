from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import web_session_dto as dto
from app.db import get_session
from app.services import web_auth, web_me
from app.web_security import ATTEMPT, SESSION, WebPrincipal, csrf, optional_principal, require_web_session

router = APIRouter(prefix="/v2", tags=["auth"])
COOKIE = dict(path="/", secure=True, httponly=True, samesite="lax")


def membership_reader() -> web_me.Memberships:
    return web_me.memberships


@router.post("/auth/telegram/challenge")
async def challenge(body: dto.TelegramExchangeRequest, response: Response,
                    db: AsyncSession = Depends(get_session)) -> dto.TelegramBrowserChallenge:
    async with db.begin():
        attempt = await web_auth.challenge(db, body.token)
        payload = dto.TelegramBrowserChallenge(confirmation_code=attempt.code, expires_at=attempt.expires_at)
    remaining = max(0, int((attempt.expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(ATTEMPT, attempt.cookie, max_age=remaining, **COOKIE)
    return payload


@router.post("/auth/telegram/exchange")
async def exchange(body: dto.TelegramExchangeRequest, request: Request, response: Response,
                   db: AsyncSession = Depends(get_session),
                   reader: web_me.Memberships = Depends(membership_reader)) -> dto.AuthSession:
    attempt = request.cookies.get(ATTEMPT)
    if not attempt:
        raise web_auth.InvalidLogin()
    async with db.begin():
        grant = await web_auth.exchange(db, body.token, attempt, request.cookies.get(SESSION))
        row = await web_auth.authenticate(db, grant.secret)
        me = await web_me.project(db, row, reader, login=True)
        payload = dto.AuthSession(csrf_token=csrf(row), me=me)
    response.set_cookie(SESSION, grant.secret, expires=grant.expires_at, **COOKIE)
    response.delete_cookie(ATTEMPT, **COOKIE)
    return payload


@router.get("/auth/csrf")
async def get_csrf(principal: WebPrincipal = Depends(require_web_session),
                   db: AsyncSession = Depends(get_session)) -> dto.CsrfToken:
    result = dto.CsrfToken(csrf_token=csrf(principal.session))
    await db.commit()
    return result


@router.get("/me")
async def get_me(principal: WebPrincipal = Depends(require_web_session), db: AsyncSession = Depends(get_session),
                 reader: web_me.Memberships = Depends(membership_reader)) -> dto.Me:
    result = await web_me.project(db, principal.session, reader, login=False)
    await db.commit()
    return result


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, principal: WebPrincipal | None = Depends(optional_principal),
                 db: AsyncSession = Depends(get_session)) -> Response:
    if principal is not None:
        await web_auth.revoke(db, request.cookies[SESSION])
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(SESSION, **COOKIE)
    return response
