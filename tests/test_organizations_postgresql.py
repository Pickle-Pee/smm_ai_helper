import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select, update

from app.models import Membership, Organization, User
from app.services import organizations as tenants, web_me
from tests.postgresql_support import mvp_database


def test_personal_onboarding_is_atomic_idempotent_and_owner_scoped(mvp_database):
    async def run():
        async with mvp_database.begin() as db:
            a, b = User(), User()
            db.add_all([a, b])
            await db.flush()
            owner, stranger = a.id, b.id

        async def provision(user_id):
            async with mvp_database.begin() as db:
                return await tenants.ensure_personal(db, user_id)

        try:
            with pytest.raises(RuntimeError):
                async with mvp_database.begin() as db:
                    await tenants.ensure_personal(db, owner)
                    raise RuntimeError("rollback onboarding")
            async with mvp_database() as db:
                assert await tenants.active_memberships(db, owner) == []
            outcomes = await asyncio.gather(*(provision(owner) for _ in range(6)))
            assert len(set(outcomes)) == 1
            org = outcomes[0]
            other = await provision(stranger)
            assert org != other
            async with mvp_database.begin() as db:
                assert await tenants.require_access(db, owner, org, "owner") == 1
                [member] = await web_me.memberships(db, owner, False)
                assert member.organization.id == org and member.role == "owner"
                assert await web_me.memberships(db, owner, True) == [member]
                with pytest.raises(tenants.TenantNotFound):
                    await tenants.require_access(db, stranger, org, "viewer")
                await db.execute(update(Membership).where(Membership.org_id == org).values(revoked_at=func.now()))
                assert await db.scalar(select(Membership.version).where(Membership.org_id == org)) == 2
            async with mvp_database.begin() as db:
                with pytest.raises(tenants.TenantNotFound):
                    await tenants.ensure_personal(db, owner)
                assert await tenants.active_memberships(db, owner) == []
                assert await tenants.require_access(db, stranger, other, "owner") == 1
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(User).where(User.id.in_([owner, stranger])))
    asyncio.run(run())


def test_role_change_and_deleted_tenant_are_visible_to_next_check(mvp_database):
    async def run():
        org_id = uuid.uuid4()
        async with mvp_database.begin() as db:
            user = User()
            db.add_all([user, Organization(id=org_id, name="Role test", kind="team")])
            await db.flush()
            user_id = user.id
            db.add(Membership(org_id=org_id, user_id=user_id, role="editor"))
        try:
            async with mvp_database.begin() as db:
                assert await tenants.require_access(db, user_id, org_id, "editor") == 1
                with pytest.raises(tenants.InsufficientRole):
                    await tenants.require_access(db, user_id, org_id, "owner")
                await db.execute(update(Membership).where(Membership.org_id == org_id).values(role="viewer"))
                assert await tenants.require_access(db, user_id, org_id, "viewer") == 2
                with pytest.raises(tenants.InsufficientRole):
                    await tenants.require_access(db, user_id, org_id, "editor")
                await db.execute(update(Organization).where(Organization.id == org_id).values(deleted_at=func.now()))
                with pytest.raises(tenants.TenantNotFound):
                    await tenants.require_access(db, user_id, org_id, "viewer")
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(Organization).where(Organization.id == org_id))
                await db.execute(delete(User).where(User.id == user_id))
    asyncio.run(run())
