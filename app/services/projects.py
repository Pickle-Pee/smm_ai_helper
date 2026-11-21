"""Project persistence in the caller's transaction."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, Project
from app.services import organizations


async def authorized_org(db: AsyncSession, user_id: int, org_id: uuid.UUID, minimum: str):
    # Serialize provisioning and membership changes through commit.
    row = (await db.execute(organizations.active_query(user_id).where(
        Organization.id == org_id).with_for_update())).one_or_none()
    if row is None:
        raise organizations.TenantNotFound()
    if organizations.ROLE_LEVEL[row.role] < organizations.ROLE_LEVEL[minimum]:
        raise organizations.InsufficientRole()
    return row


async def ensure_default(db: AsyncSession, user_id: int, org_id: uuid.UUID):
    org = await authorized_org(db, user_id, org_id, "owner")
    if org.kind != "personal":
        raise organizations.InsufficientRole()
    project = await db.scalar(select(Project).where(Project.org_id == org_id, Project.default_for_user == user_id))
    if project is None:
        project = Project(org_id=org_id, default_for_user=user_id, created_by=user_id, name="Мой проект")
        db.add(project)
        await db.flush()
    return project
