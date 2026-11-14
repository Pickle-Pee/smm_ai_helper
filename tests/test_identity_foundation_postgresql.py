"""B1a identity foundation against real PostgreSQL constraints and triggers.

Disposable ``smm_mvp_test`` database only; no provider, Telegram or network calls.
Every test removes the users it creates, so later migration downgrades in the
same database never meet a web-only user.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config import settings
from app.db import get_session
from app.models import BrandProfile, ExternalIdentity, MarketingRun, Task, User
from app.routers import brand_profile_router, tasks_router
from app.schemas import UserCreate
from app.services.identity_service import (
    IdentityConflictError, IdentityService, telegram_subject,
)
from app.services.user_service import UserService
from bot.backend import actor_headers
from tests.postgresql_support import mvp_database


def new_actor() -> int:
    return int(uuid.uuid4().hex[:12], 16) + 1


async def bot_upsert(db, actor):
    """The exact legacy creation path used by Copilot, workflows, chat and project context."""
    await db.execute(insert(User).values(telegram_id=actor).on_conflict_do_nothing(index_elements=[User.telegram_id]))
    return await db.scalar(select(User.id).where(User.telegram_id == actor))


async def identities_of(db, user_id):
    rows = await db.scalars(select(ExternalIdentity).where(ExternalIdentity.user_id == user_id)
                            .order_by(ExternalIdentity.provider))
    return list(rows)


async def drop_users(sessions, *user_ids):
    async with sessions() as db, db.begin():
        for model in (Task, BrandProfile, MarketingRun):
            await db.execute(delete(model).where(model.user_id.in_(user_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))


async def sqlstate(db, statement):
    """Run one statement in its own savepoint and return the PostgreSQL error code."""
    with pytest.raises((IntegrityError, DBAPIError)) as failure:
        async with db.begin_nested():
            await db.execute(statement)
    return failure.value.orig.sqlstate


def test_canonical_telegram_subject_matches_require_actor_range():
    assert telegram_subject(1) == "1"
    assert telegram_subject(2**63 - 1) == str(2**63 - 1)
    for bad in (0, -1, 2**63, True, "123", 1.0):
        with pytest.raises(ValueError):
            telegram_subject(bad)


def test_telegram_user_creation_paths_get_exactly_one_verified_identity(mvp_database):
    async def run():
        upsert_actor, orm_actor = new_actor(), new_actor()
        async with mvp_database() as db, db.begin():
            first = await bot_upsert(db, upsert_actor)
            assert await bot_upsert(db, upsert_actor) == first  # replayed first request
            created = await UserService.get_or_create(db, UserCreate(telegram_id=orm_actor, username="legacy"))
            ids = (first, created.id)
        try:
            async with mvp_database() as db:
                for user_id, actor in zip(ids, (upsert_actor, orm_actor)):
                    [identity] = await identities_of(db, user_id)
                    assert (identity.provider, identity.subject, identity.telegram_id) == ("telegram", str(actor), actor)
                    assert identity.verified_at is not None and identity.created_at is not None
                    assert await IdentityService.resolve_telegram_user_id(db, actor) == user_id
                    assert (await UserService.get_by_telegram_id(db, actor)).id == user_id
                assert await IdentityService.resolve_telegram_user_id(db, new_actor()) is None
        finally:
            await drop_users(mvp_database, *ids)
    asyncio.run(run())


def test_web_only_user_has_null_telegram_id_and_does_not_disturb_telegram_queries(mvp_database):
    async def run():
        actor = new_actor()
        async with mvp_database() as db, db.begin():
            web_a, web_b = User(first_name="Web A"), User(first_name="Web B")
            db.add_all([web_a, web_b])  # NULL is not a duplicate Telegram id
            await db.flush()
            telegram_owner = await bot_upsert(db, actor)
            ids = (web_a.id, web_b.id, telegram_owner)
        try:
            async with mvp_database() as db:
                assert await db.scalar(select(User.telegram_id).where(User.id == web_a.id)) is None
                assert await identities_of(db, web_a.id) == []
                # Telegram lookups and owner joins only ever match the real actor.
                assert (await UserService.get_by_telegram_id(db, actor)).id == telegram_owner
                assert await db.scalar(select(func.count()).select_from(User).where(User.telegram_id == actor)) == 1
                assert await IdentityService.unmatched_telegram_users(db) == 0
        finally:
            await drop_users(mvp_database, *ids)
    asyncio.run(run())


def test_telegram_id_and_provider_subject_are_unique(mvp_database):
    async def run():
        actor = new_actor()
        async with mvp_database() as db, db.begin():
            owner = await bot_upsert(db, actor)
            other = User()
            db.add(other)
            await db.flush()
            ids = (owner, other.id)
        try:
            async with mvp_database() as db, db.begin():
                assert await sqlstate(db, insert(User).values(telegram_id=actor)) == "23505"
                email = {"provider": "email", "subject": "owner@example.test",
                         "verified_at": datetime.now(timezone.utc)}
                await db.execute(insert(ExternalIdentity).values(user_id=owner, **email))
                assert await sqlstate(db, insert(ExternalIdentity).values(user_id=other.id, **email)) == "23505"
                assert await sqlstate(db, insert(ExternalIdentity).values(user_id=owner, **email)) == "23505"
        finally:
            await drop_users(mvp_database, *ids)
    asyncio.run(run())


def test_one_user_can_hold_several_independent_identities(mvp_database):
    async def run():
        actor, now = new_actor(), datetime.now(timezone.utc)
        async with mvp_database() as db, db.begin():
            owner = await bot_upsert(db, actor)
            await db.execute(insert(ExternalIdentity), [
                {"user_id": owner, "provider": "email", "subject": f"{actor}@example.test", "verified_at": now},
                {"user_id": owner, "provider": "oidc:example-issuer", "subject": "sub-123", "verified_at": now},
            ])
        try:
            async with mvp_database() as db:
                assert [i.provider for i in await identities_of(db, owner)] == ["email", "oidc:example-issuer", "telegram"]
                assert await IdentityService.resolve_user_id(db, "email", f"{actor}@example.test") == owner
                assert await IdentityService.resolve_user_id(db, "oidc:example-issuer", "sub-123") == owner
        finally:
            await drop_users(mvp_database, owner)
    asyncio.run(run())


def test_a_telegram_identity_cannot_be_bound_to_another_user_or_relinked(mvp_database):
    async def run():
        actor, stranger_actor, now = new_actor(), new_actor(), datetime.now(timezone.utc)
        async with mvp_database() as db, db.begin():
            owner = await bot_upsert(db, actor)
            stranger = await bot_upsert(db, stranger_actor)
            web = User()
            db.add(web)
            await db.flush()
            ids = (owner, stranger, web.id)
        try:
            async with mvp_database() as db, db.begin():
                steal = {"provider": "telegram", "subject": str(actor), "verified_at": now}
                # Same subject for another user: unique (provider, subject) and composite FK.
                assert await sqlstate(db, insert(ExternalIdentity).values(user_id=stranger, telegram_id=actor, **steal)) in {"23505", "23503"}
                assert await sqlstate(db, insert(ExternalIdentity).values(user_id=web.id, telegram_id=actor, **steal)) in {"23505", "23503"}
                # A fresh Telegram id may not be attached to a user that does not own it.
                fresh = new_actor()
                assert await sqlstate(db, insert(ExternalIdentity).values(
                    user_id=web.id, provider="telegram", subject=str(fresh), telegram_id=fresh, verified_at=now)) == "23503"
                assert await sqlstate(db, insert(ExternalIdentity).values(
                    user_id=web.id, provider="telegram", subject=str(fresh), verified_at=now)) == "23514"
                assert await sqlstate(db, insert(ExternalIdentity).values(
                    user_id=owner, provider="telegram", subject="0" + str(actor), telegram_id=actor, verified_at=now)) == "23514"
                assert await sqlstate(db, insert(ExternalIdentity).values(
                    user_id=owner, provider="unknown", subject="x", verified_at=now)) == "23514"
                # Moving the existing identity, or re-keying / linking users.telegram_id, is refused.
                assert await sqlstate(db, update(ExternalIdentity).where(
                    ExternalIdentity.subject == str(actor)).values(user_id=stranger)) == "23503"
                for user_id, value in ((owner, new_actor()), (owner, None), (web.id, new_actor())):
                    assert await sqlstate(db, update(User).where(User.id == user_id).values(telegram_id=value)) == "23001"
            async with mvp_database() as db:
                assert await IdentityService.resolve_telegram_user_id(db, actor) == owner
                assert await db.scalar(select(User.telegram_id).where(User.id == web.id)) is None
        finally:
            await drop_users(mvp_database, *ids)
    asyncio.run(run())


def test_backfill_is_idempotent_and_never_moves_ownership(mvp_database):
    async def run():
        actors = [new_actor() for _ in range(3)]
        run_ids = []
        async with mvp_database() as db, db.begin():
            owners = [await bot_upsert(db, actor) for actor in actors]
            for owner in owners:
                run_id = uuid.uuid4().hex
                run_ids.append(run_id)
                db.add_all([
                    Task(user_id=owner, agent_type="strategy", task_description="history", status="done"),
                    BrandProfile(user_id=owner, brand_name=f"Brand {owner}"),
                    MarketingRun(run_id=run_id, user_id=owner, workflow_type="marketing_mvp.v1", status="completed"),
                ])
            # Simulate rows that pre-date B1a (or a repair after manual cleanup).
            await db.execute(delete(ExternalIdentity).where(ExternalIdentity.user_id.in_(owners[:2])))

        async def snapshot():
            async with mvp_database() as db:
                return (
                    sorted((await db.execute(select(User.id, User.telegram_id).where(User.id.in_(owners)))).all()),
                    sorted((await db.execute(select(Task.id, Task.user_id).where(Task.user_id.in_(owners)))).all()),
                    sorted((await db.execute(select(BrandProfile.id, BrandProfile.user_id).where(BrandProfile.user_id.in_(owners)))).all()),
                    sorted((await db.execute(select(MarketingRun.run_id, MarketingRun.user_id).where(MarketingRun.run_id.in_(run_ids)))).all()),
                )
        try:
            before = await snapshot()
            async with mvp_database() as db:
                assert await IdentityService.unmatched_telegram_users(db) == 2
            async with mvp_database() as db, db.begin():
                first = await IdentityService.backfill_telegram_identities(db)
            async with mvp_database() as db, db.begin():
                second = await IdentityService.backfill_telegram_identities(db)
            assert (first.created, second.created) == (2, 0)
            assert first.telegram_users == second.telegram_users >= 3
            assert await snapshot() == before
            async with mvp_database() as db:
                for owner, actor in zip(owners, actors):
                    [identity] = await identities_of(db, owner)
                    assert identity.subject == str(actor)
                assert await IdentityService.unmatched_telegram_users(db) == 0
        finally:
            await drop_users(mvp_database, *owners)
    asyncio.run(run())


def test_backfill_conflict_fails_visibly_and_rolls_back_without_reassignment(mvp_database):
    """Defense in depth: even data that bypassed constraints is never silently re-owned."""
    async def run():
        victim_actor, other_actor = new_actor(), new_actor()
        async with mvp_database() as db, db.begin():
            victim = await bot_upsert(db, victim_actor)
            other = await bot_upsert(db, other_actor)
            fixable = await bot_upsert(db, new_actor())
            await db.execute(delete(ExternalIdentity).where(ExternalIdentity.user_id.in_((victim, fixable))))
        try:
            async with mvp_database() as db, db.begin():
                try:
                    await db.execute(text("SET LOCAL session_replication_role = replica"))
                except DBAPIError:
                    pytest.skip("Corruption simulation needs a superuser on the disposable database")
                # A corrupt row binds the victim's Telegram id to another user.
                await db.execute(insert(ExternalIdentity).values(
                    user_id=other, provider="telegram", subject=str(victim_actor),
                    telegram_id=victim_actor, verified_at=datetime.now(timezone.utc)))
            async with mvp_database() as db:
                with pytest.raises(IdentityConflictError):
                    async with db.begin():
                        await IdentityService.backfill_telegram_identities(db)
            async with mvp_database() as db:
                # Atomic: the fixable user was not partially repaired; nothing changed owner.
                assert await identities_of(db, fixable) == []
                assert await identities_of(db, victim) == []
                assert await IdentityService.resolve_telegram_user_id(db, victim_actor) == other
                assert await db.scalar(select(User.telegram_id).where(User.id == victim)) == victim_actor
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(ExternalIdentity).where(
                    ExternalIdentity.user_id == other, ExternalIdentity.subject == str(victim_actor)))
            async with mvp_database() as db, db.begin():
                await IdentityService.backfill_telegram_identities(db)
            await drop_users(mvp_database, victim, other, fixable)
    asyncio.run(run())


def test_concurrent_first_requests_and_bindings_resolve_atomically(mvp_database):
    async def run():
        actor = new_actor()

        async def first_request():
            async with mvp_database() as db, db.begin():
                return await bot_upsert(db, actor)
        owners = set(await asyncio.gather(*(first_request() for _ in range(6))))
        assert len(owners) == 1
        [owner] = owners
        async with mvp_database() as db, db.begin():
            rivals = [User(), User()]
            db.add_all(rivals)
            await db.flush()
            rival_ids = [rival.id for rival in rivals]

        async def bind(user_id):
            async with mvp_database() as db:
                try:
                    async with db.begin():
                        await db.execute(insert(ExternalIdentity).values(
                            user_id=user_id, provider="email", subject=f"race-{actor}@example.test",
                            verified_at=datetime.now(timezone.utc)))
                    return user_id
                except IntegrityError:
                    return None
        try:
            async with mvp_database() as db:
                assert len(await identities_of(db, owner)) == 1
            results = await asyncio.gather(*(bind(user_id) for user_id in rival_ids))
            winners = [result for result in results if result is not None]
            assert len(winners) == 1
            async with mvp_database() as db:
                assert await IdentityService.resolve_user_id(db, "email", f"race-{actor}@example.test") == winners[0]
        finally:
            await drop_users(mvp_database, owner, *rival_ids)
    asyncio.run(run())


def test_legacy_bot_endpoints_keep_their_owner_and_still_require_the_bot_token(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "b1a-service-secret")
    app = FastAPI()
    app.include_router(tasks_router)
    app.include_router(brand_profile_router)

    async def session():
        async with mvp_database() as db:
            yield db
    app.dependency_overrides[get_session] = session

    async def run():
        actor = new_actor()
        async with mvp_database() as db, db.begin():
            owner = await bot_upsert(db, actor)
            db.add_all([Task(user_id=owner, agent_type="strategy", task_description="kept history", status="done"),
                        BrandProfile(user_id=owner, brand_name="Kept brand")])
            web = User()
            db.add(web)
            await db.flush()
            ids = (owner, web.id)
        bot = {"Authorization": "Bearer b1a-service-secret"}
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                history = await client.get(f"/tasks/by_user/{actor}", headers={**bot, **actor_headers(actor)})
                profile = await client.get(f"/brand-profile/{actor}", headers={**bot, **actor_headers(actor)})
                assert history.status_code == 200 and [t["task_description"] for t in history.json()] == ["kept history"]
                assert profile.status_code == 200 and profile.json()["brand_name"] == "Kept brand"
                # An existing identity grants nothing without the service credential.
                for headers in ({"X-Telegram-User-ID": str(actor)}, bot,
                                {"Authorization": "Bearer wrong", "X-Telegram-User-ID": str(actor)}):
                    assert (await client.get(f"/brand-profile/{actor}", headers=headers)).status_code == 401
                assert (await client.get(f"/brand-profile/{actor}",
                                         headers={**bot, **actor_headers(new_actor())})).status_code == 403
        finally:
            await drop_users(mvp_database, *ids)
    asyncio.run(run())
