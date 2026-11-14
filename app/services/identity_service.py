"""B1a identity data layer: resolution and idempotent Telegram identity repair.

Scope is deliberately narrow. There is no login, no linking of an identity to an
existing user and no account merge here (Web API v2 §5.3, D17/OQ-5). Telegram
identities are written only by PostgreSQL itself (migration backfill and the
``users_mirror_telegram_identity`` trigger) and by the explicit repair below,
which only ever binds a Telegram id to the user that already owns it in
``users.telegram_id``. Legacy bot authorization (``require_bot``/``require_actor``)
does not use this module.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExternalIdentity, User

TELEGRAM = "telegram"

_BACKFILL = text("""
INSERT INTO external_identities (user_id, provider, subject, telegram_id, verified_at, created_at)
SELECT id, 'telegram', telegram_id::text, telegram_id, created_at AT TIME ZONE 'UTC', now()
FROM users
WHERE telegram_id IS NOT NULL
ON CONFLICT (provider, subject) DO NOTHING
""")


class IdentityConflictError(RuntimeError):
    """Stored identities disagree with ``users.telegram_id``; nothing is reassigned."""


@dataclass(frozen=True)
class TelegramBackfillReport:
    telegram_users: int
    created: int


def telegram_subject(telegram_id: int) -> str:
    """Canonical Telegram subject: the exact positive numeric id, as accepted by ``require_actor``."""
    if type(telegram_id) is not int or not 0 < telegram_id < 2**63:
        raise ValueError("Telegram id must be a positive 64-bit integer")
    return str(telegram_id)


class IdentityService:
    @staticmethod
    async def resolve_user_id(session: AsyncSession, provider: str, subject: str) -> int | None:
        """Return the owning ``users.id`` of a verified identity, or None. Never creates anything."""
        return await session.scalar(select(ExternalIdentity.user_id).where(
            ExternalIdentity.provider == provider, ExternalIdentity.subject == subject))

    @classmethod
    async def resolve_telegram_user_id(cls, session: AsyncSession, telegram_id: int) -> int | None:
        return await cls.resolve_user_id(session, TELEGRAM, telegram_subject(telegram_id))

    @staticmethod
    async def unmatched_telegram_users(session: AsyncSession) -> int:
        """Count Telegram users without their own identity row (0 when consistent)."""
        own = exists().where(and_(
            ExternalIdentity.provider == TELEGRAM, ExternalIdentity.user_id == User.id,
            ExternalIdentity.telegram_id == User.telegram_id,
        ))
        return await session.scalar(
            select(func.count()).select_from(User).where(User.telegram_id.is_not(None), ~own))

    @classmethod
    async def backfill_telegram_identities(cls, session: AsyncSession) -> TelegramBackfillReport:
        """Idempotently create missing Telegram identities for their existing owners.

        The caller owns the transaction. On ``IdentityConflictError`` it must roll
        back: the inserted rows are discarded and no existing row is changed.
        """
        created = (await session.execute(_BACKFILL)).rowcount
        unmatched = await cls.unmatched_telegram_users(session)
        if unmatched:
            raise IdentityConflictError(
                f"{unmatched} Telegram users have no identity of their own; refusing to reassign")
        total = await session.scalar(
            select(func.count()).select_from(User).where(User.telegram_id.is_not(None)))
        return TelegramBackfillReport(telegram_users=total, created=created)
