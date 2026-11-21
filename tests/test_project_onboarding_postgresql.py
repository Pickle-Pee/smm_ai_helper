import asyncio

import pytest
from sqlalchemy import delete, event, func, select

from app.models import BrandProfile, LoginToken, Organization, Project, ProjectBrand, User, WebSession
from app.services import organizations, project_onboarding, web_auth
from tests.postgresql_support import mvp_database
from tests.test_web_auth_postgresql import actors, call, prepared


def test_parallel_first_login_and_one_time_copy(mvp_database, actors):
    async def login(actor):
        grant, attempt = await prepared(mvp_database, actor)
        async with mvp_database.begin() as db:
            session = await web_auth.exchange(db, grant.secret, attempt.cookie)
            live = await web_auth.authenticate(db, session.secret)
            await project_onboarding.initialize(db, live.user_id)
            return live.user_id

    async def run():
        async with mvp_database.begin() as db:
            owner = await db.scalar(select(User.id).where(User.telegram_id == actors[0]))
            legacy = BrandProfile(user_id=owner, brand_name="Original", extra_json={"industry": "Books", "secret": "x"})
            db.add(legacy)
        try:
            first, second = await asyncio.gather(login(actors[0]), login(actors[0]))
            assert first == second == owner
            other = await login(actors[1])
            async with mvp_database.begin() as db:
                brands = select(ProjectBrand).join(Project).where(Project.default_for_user == owner)
                brand = (await db.scalars(brands)).one()
                assert brand.imported_by == owner and brand.source_profile_id == legacy.id
                assert brand.extra_json == {"industry": "Books"} and brand.brand_name == "Original"
                with pytest.raises(organizations.TenantNotFound):
                    await project_onboarding.import_personal_brand(db, other, brand)
                brand.brand_name = "Edited in web"
                db.add(BrandProfile(user_id=other, brand_name="Late Telegram profile"))
            await login(actors[0])
            await login(actors[1])
            async with mvp_database() as db:
                assert (await db.scalar(brands)).brand_name == "Edited in web"
                empty = await db.scalar(select(ProjectBrand).join(Project).where(Project.default_for_user == other))
                assert empty.imported_at is None and empty.brand_name is None
                assert (await db.get(BrandProfile, legacy.id)).brand_name == "Original"
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(BrandProfile).where(BrandProfile.user_id.in_(
                    select(User.id).where(User.telegram_id.in_(actors)))))
    asyncio.run(run())


@pytest.mark.parametrize("after", ["token", "revoke", "session", "org", "membership", "project", "brand"])
def test_failure_after_write_keeps_previous_session_and_grant(mvp_database, actors, after):
    async def run():
        grant, attempt = await prepared(mvp_database, actors[0])
        previous = await call(mvp_database, web_auth.exchange, grant.secret, attempt.cookie)
        grant, attempt = await prepared(mvp_database, actors[0])
        statements = {"token": "update " + LoginToken.__tablename__, "revoke": "update web_sessions",
                      "session": "insert into web_sessions", "org": "insert into organizations",
                      "membership": "insert into memberships", "project": "insert into projects",
                      "brand": "insert into project_brands"}
        def fail(conn, cursor, statement, parameters, context, many):
            if statement.lower().startswith(statements[after]):
                raise RuntimeError("injected failure")
        with pytest.raises(RuntimeError, match="injected failure"):
            async with mvp_database.begin() as db:
                connection = await db.connection()
                event.listen(connection.sync_connection, "after_cursor_execute", fail)
                session = await web_auth.exchange(db, grant.secret, attempt.cookie, previous.secret)
                live = await web_auth.authenticate(db, session.secret)
                await project_onboarding.initialize(db, live.user_id)
        live = await call(mvp_database, web_auth.authenticate, previous.secret)
        assert live
        async with mvp_database() as db:
            assert await db.scalar(select(func.count()).select_from(Organization).where(
                Organization.personal_user_id == live.user_id)) == 0
            assert await db.scalar(select(func.count()).select_from(WebSession).where(WebSession.user_id == live.user_id)) == 1
        assert await call(mvp_database, web_auth.exchange, grant.secret, attempt.cookie, previous.secret)
    asyncio.run(run())
