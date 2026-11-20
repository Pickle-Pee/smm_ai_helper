"""B2.1 transactions against disposable PostgreSQL (including actual competing connections)."""
import asyncio
import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.models import BrowserAttempt, LoginToken, User, WebSession
from app.services import web_auth as auth
from tests.postgresql_support import mvp_database


@pytest.fixture
def actors(mvp_database):
    values = [uuid.uuid4().int >> 80 for _ in range(2)]

    async def seed():
        async with mvp_database.begin() as db:
            db.add_all([User(telegram_id=value) for value in values])

    async def remove():
        async with mvp_database.begin() as db:
            await db.execute(delete(User).where(User.telegram_id.in_(values)))

    asyncio.run(seed())
    try:
        yield values
    finally:
        asyncio.run(remove())


async def call(factory, fn, *args):
    async with factory.begin() as db:
        return await fn(db, *args)


async def prepared(factory, actor):
    grant = await call(factory, auth.issue, actor)
    attempt = await call(factory, auth.challenge, grant.secret)
    await call(factory, auth.confirm, actor, attempt.code)
    return grant, attempt


def test_actor_browser_and_link_binding(mvp_database, actors, caplog):
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine")

    async def run():
        owner, other = actors
        grant = await call(mvp_database, auth.issue, owner)
        attempt = await call(mvp_database, auth.challenge, grant.secret)
        alien, alien_attempt = await prepared(mvp_database, other)
        with pytest.raises(auth.InvalidLogin):
            await call(mvp_database, auth.confirm, other, attempt.code)
        with pytest.raises(auth.InvalidLogin):
            await call(mvp_database, auth.exchange, grant.secret, attempt.cookie)
        await call(mvp_database, auth.confirm, owner, attempt.code)
        with pytest.raises(auth.InvalidLogin):
            await call(mvp_database, auth.confirm, owner, attempt.code)
        with pytest.raises(auth.InvalidLogin):
            await call(mvp_database, auth.exchange, alien.secret, attempt.cookie)
        previous = await call(mvp_database, auth.exchange, alien.secret, alien_attempt.cookie)
        # An outer failure (including future onboarding failure) rolls back all three writes.
        with pytest.raises(RuntimeError, match="rollback probe"):
            async with mvp_database.begin() as db:
                await auth.exchange(db, grant.secret, attempt.cookie, previous.secret)
                raise RuntimeError("rollback probe")
        assert await call(mvp_database, auth.authenticate, previous.secret)
        session = await call(mvp_database, auth.exchange, grant.secret, attempt.cookie, previous.secret)
        assert await call(mvp_database, auth.authenticate, previous.secret) is None
        live = await call(mvp_database, auth.authenticate, session.secret)
        async with mvp_database() as db:
            assert live.user_id == await db.scalar(select(User.id).where(User.telegram_id == owner))
        with pytest.raises(auth.InvalidLogin):
            await call(mvp_database, auth.exchange, grant.secret, attempt.cookie)
        for value in (grant.secret, attempt.cookie, attempt.code, session.secret, previous.secret):
            assert value not in caplog.text
            assert value not in repr((grant, attempt, session, previous))

    asyncio.run(run())


def test_concurrent_issue_claim_exchange_and_logout(mvp_database, actors):
    async def race(fn, args, n, error):
        results = await asyncio.gather(*(call(mvp_database, fn, *args) for _ in range(n)), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(result, error):
                raise result
        return [r for r in results if not isinstance(r, error)]

    async def run():
        actor = actors[0]
        grants = await race(auth.issue, (actor,), 7, auth.IssueLimitExceeded)
        assert len(grants) == auth.ISSUE_LIMIT
        grant = grants[0]
        [attempt] = await race(auth.challenge, (grant.secret,), 4, auth.InvalidLogin)
        await call(mvp_database, auth.confirm, actor, attempt.code)
        [session] = await race(auth.exchange, (grant.secret, attempt.cookie), 4, auth.InvalidLogin)
        await asyncio.gather(call(mvp_database, auth.authenticate, session.secret),
                             call(mvp_database, auth.revoke, session.secret))
        assert await call(mvp_database, auth.authenticate, session.secret) is None

    asyncio.run(run())


def test_expiration_idle_cap_and_cleanup(mvp_database, actors):
    async def run():
        grant, attempt = await prepared(mvp_database, actors[0])
        valid = await call(mvp_database, auth.exchange, grant.secret, attempt.cookie)
        session = await call(mvp_database, auth.authenticate, valid.secret)
        assert valid.expires_at - session.created_at == auth.ABSOLUTE_TTL
        assert auth.IDLE_TTL <= session.idle_expires_at - session.created_at < auth.IDLE_TTL + timedelta(minutes=1)
        expiring, exp_attempt = await prepared(mvp_database, actors[1])
        async with mvp_database.begin() as db:
            now = await db.scalar(select(func.clock_timestamp()))
            owner = await db.scalar(select(User.id).where(User.telegram_id == actors[1]))
            token_id = await db.scalar(update(LoginToken).where(LoginToken.user_id == owner)
                                       .values(created_at=now-auth.LINK_TTL, expires_at=now).returning(LoginToken.id))
            await db.execute(update(WebSession).where(WebSession.id == session.id).values(
                created_at=now-timedelta(days=29), idle_expires_at=now+timedelta(hours=1),
                absolute_expires_at=now+timedelta(days=1)))
        with pytest.raises(auth.InvalidLogin):
            await call(mvp_database, auth.exchange, expiring.secret, exp_attempt.cookie)
        capped = await call(mvp_database, auth.authenticate, valid.secret)
        assert capped.idle_expires_at == capped.absolute_expires_at
        async with mvp_database.begin() as db:
            await db.execute(update(WebSession).where(WebSession.id == session.id)
                             .values(idle_expires_at=func.clock_timestamp()))
        assert await call(mvp_database, auth.authenticate, valid.secret) is None
        # An absolute deadline remains terminal even when the request carries the correct cookie.
        async with mvp_database.begin() as db:
            now = await db.scalar(select(func.clock_timestamp()))
            await db.execute(update(WebSession).where(WebSession.id == session.id).values(
                created_at=now-auth.ABSOLUTE_TTL, idle_expires_at=now, absolute_expires_at=now))
        assert await call(mvp_database, auth.authenticate, valid.secret) is None
        await call(mvp_database, auth.cleanup)
        async with mvp_database() as db:
            assert await db.get(WebSession, session.id) is None
            assert await db.get(BrowserAttempt, token_id) is None
            assert await db.get(LoginToken, token_id) is None

    asyncio.run(run())


def test_expiry_while_waiting_for_previous_session_preserves_old_cookie(mvp_database, actors, monkeypatch):
    async def run():
        old_link, old_attempt = await prepared(mvp_database, actors[0])
        previous = await call(mvp_database, auth.exchange, old_link.secret, old_attempt.cookie)
        grant, attempt = await prepared(mvp_database, actors[1])
        # PostgreSQL time sampled before and after acquiring the previous session lock.
        times = iter([grant.expires_at - timedelta(seconds=1), grant.expires_at])

        async def sample_time(db):
            return next(times)

        with monkeypatch.context() as patch:
            patch.setattr(auth, "_now", sample_time)
            async with mvp_database.begin() as db:
                with pytest.raises(auth.InvalidLogin):
                    await auth.exchange(db, grant.secret, attempt.cookie, previous.secret)
        assert await call(mvp_database, auth.authenticate, previous.secret)

    asyncio.run(run())
