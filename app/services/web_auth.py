"""B2.1 persistence boundary. Caller owns the transaction and releases secrets only after commit."""
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BrowserAttempt, LoginToken, User, WebSession
from app.services.identity_service import IdentityService

LINK_TTL = timedelta(minutes=10)
IDLE_TTL = timedelta(days=7)
ABSOLUTE_TTL = timedelta(days=30)
ISSUE_LIMIT = 5


class InvalidLogin(ValueError):
    """Uniform failure for unknown, expired, replayed or mismatched credentials."""


class IssueLimitExceeded(ValueError):
    pass


@dataclass(frozen=True)
class Grant:
    secret: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class Challenge:
    cookie: str = field(repr=False)
    code: str = field(repr=False)
    expires_at: datetime


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _now(db: AsyncSession) -> datetime:
    # Transaction start time can precede a wait on a competing exchange.
    return await db.scalar(select(func.clock_timestamp()))


async def issue(db: AsyncSession, telegram_actor: int) -> Grant:
    owner = await IdentityService.resolve_telegram_user_id(db, telegram_actor)
    if owner is None:
        raise InvalidLogin()
    await db.execute(select(User.id).where(User.id == owner).with_for_update())
    now = await _now(db)
    count = await db.scalar(select(func.count()).select_from(LoginToken).where(
        LoginToken.user_id == owner, LoginToken.created_at > now - LINK_TTL))
    if count >= ISSUE_LIMIT:
        raise IssueLimitExceeded()
    token = secrets.token_urlsafe(32)
    expires = now + LINK_TTL
    db.add(LoginToken(user_id=owner, token_hash=_hash(token), created_at=now, expires_at=expires))
    await db.flush()
    return Grant(token, expires)


async def _lock_live_token(db, query):
    token = await db.scalar(query.with_for_update(of=LoginToken).execution_options(populate_existing=True))
    now = await _now(db)
    if token is None or token.consumed_at is not None or token.expires_at <= now:
        raise InvalidLogin()
    return token, now


async def challenge(db: AsyncSession, secret: str) -> Challenge:
    token, _ = await _lock_live_token(db, select(LoginToken).where(LoginToken.token_hash == _hash(secret)))
    if await db.get(BrowserAttempt, token.id) is not None:
        raise InvalidLogin()
    cookie, code = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    db.add(BrowserAttempt(token_id=token.id, cookie_hash=_hash(cookie), code_hash=_hash(code)))
    await db.flush()
    return Challenge(cookie, code, token.expires_at)


async def confirm(db: AsyncSession, telegram_actor: int, code: str) -> None:
    owner = await IdentityService.resolve_telegram_user_id(db, telegram_actor)
    token, now = await _lock_live_token(db, select(LoginToken).join(BrowserAttempt).where(
        LoginToken.user_id == owner, BrowserAttempt.code_hash == _hash(code)))
    result = await db.execute(update(BrowserAttempt).where(
        BrowserAttempt.token_id == token.id, BrowserAttempt.confirmed_at.is_(None)
    ).values(confirmed_at=now))
    if result.rowcount != 1:
        raise InvalidLogin()


async def revoke(db: AsyncSession, cookie: str) -> None:
    await db.execute(update(WebSession).where(
        WebSession.token_hash == _hash(cookie), WebSession.revoked_at.is_(None)
    ).values(revoked_at=func.clock_timestamp()))


async def exchange(db: AsyncSession, secret: str, attempt_cookie: str, previous_cookie: str | None = None) -> Grant:
    token, _ = await _lock_live_token(db, select(LoginToken).join(BrowserAttempt).where(
        LoginToken.token_hash == _hash(secret), BrowserAttempt.cookie_hash == _hash(attempt_cookie),
        BrowserAttempt.confirmed_at.is_not(None)))
    if previous_cookie is not None:
        await revoke(db, previous_cookie)
    now = await _now(db)
    if token.expires_at <= now:
        raise InvalidLogin()
    token.consumed_at = now
    cookie = secrets.token_urlsafe(32)
    db.add(WebSession(user_id=token.user_id, token_hash=_hash(cookie), created_at=now,
                      idle_expires_at=now + IDLE_TTL, absolute_expires_at=now + ABSOLUTE_TTL))
    await db.flush()
    return Grant(cookie, now + ABSOLUTE_TTL)


async def authenticate(db: AsyncSession, cookie: str) -> WebSession | None:
    row = await db.scalar(select(WebSession).where(WebSession.token_hash == _hash(cookie))
                          .with_for_update().execution_options(populate_existing=True))
    now = await _now(db)
    if row is None or row.revoked_at is not None or min(row.idle_expires_at, row.absolute_expires_at) <= now:
        return None
    row.idle_expires_at = min(now + IDLE_TTL, row.absolute_expires_at)
    await db.flush()
    return row


async def cleanup(db: AsyncSession) -> tuple[int, int]:
    """Remove expired credentials. Attempts cascade. Keep consumed links for the issuance budget."""
    now = await _now(db)
    tokens = await db.execute(delete(LoginToken).where(LoginToken.expires_at <= now))
    sessions = await db.execute(delete(WebSession).where(WebSession.idle_expires_at <= now))
    return tokens.rowcount, sessions.rowcount
