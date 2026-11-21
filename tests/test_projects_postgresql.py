import asyncio

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.models import Project, ProjectBrand, User
from app.services import organizations, projects
from tests.postgresql_support import mvp_database


def test_personal_default_and_org_constraints(mvp_database):
    async def run():
        async with mvp_database() as db:
            a, b = User(), User()
            db.add_all([a, b])
            await db.flush()
            org = await organizations.ensure_personal(db, a.id)
            other = await organizations.ensure_personal(db, b.id)
            default = await projects.ensure_default(db, a.id, org)
            assert default.id == (await projects.ensure_default(db, a.id, org)).id
            with pytest.raises(organizations.TenantNotFound):
                await projects.ensure_default(db, b.id, org)
            db.add(Project(org_id=org, name="Additional", created_by=a.id))
            await db.flush()
            for invalid in (
                Project(org_id=other, default_for_user=a.id, created_by=a.id, name="Wrong owner"),
                Project(org_id=org, default_for_user=a.id, created_by=a.id, name="Duplicate"),
                ProjectBrand(project_id=default.id, org_id=other),
            ):
                with pytest.raises(IntegrityError):
                    async with db.begin_nested():
                        db.add(invalid)
                        await db.flush()
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    await db.execute(update(Project).where(Project.id == default.id).values(org_id=other))
            db.add(ProjectBrand(project_id=default.id, org_id=org))
            await db.flush()
    asyncio.run(run())
