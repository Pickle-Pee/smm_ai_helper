"""Tenant authorization and provisioning. All writes use the caller's transaction."""
import uuid

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import web_session_dto as dto
from app.models import Membership, Organization

ROLE_LEVEL = {"viewer": 1, "editor": 2, "owner": 3}


class TenantNotFound(Exception):
    pass


class InsufficientRole(Exception):
    pass


def _active(user_id: int):
    return select(Organization.id, Organization.name, Organization.kind, Organization.created_at,
                  Membership.role, Membership.joined_at, Membership.version).join(Membership).where(
        Membership.user_id == user_id, Membership.revoked_at.is_(None), Organization.deleted_at.is_(None),
        or_(Organization.kind == "team", (Organization.personal_user_id == user_id) & (Membership.role == "owner")))


async def active_memberships(db: AsyncSession, user_id: int) -> list[dto.OrganizationMembership]:
    rows = await db.execute(_active(user_id).order_by(Organization.id))
    return [dto.OrganizationMembership(
        organization=dto.Organization(id=r.id, kind=r.kind, name=r.name, created_at=r.created_at),
        role=r.role, joined_at=r.joined_at) for r in rows]


async def require_access(db: AsyncSession, user_id: int, org_id: uuid.UUID, minimum: str) -> int:
    """Return current membership version for rechecks at the delegated-read boundary."""
    row = (await db.execute(_active(user_id).where(Organization.id == org_id))).one_or_none()
    if row is None:
        raise TenantNotFound()
    if ROLE_LEVEL[row.role] < ROLE_LEVEL[minimum]:
        raise InsufficientRole()
    return row.version


async def ensure_personal(db: AsyncSession, user_id: int) -> uuid.UUID:
    """Only a newly created org receives an owner row. Never restore revoked access on login."""
    new_id = await db.scalar(insert(Organization).values(
        id=uuid.uuid4(), personal_user_id=user_id, kind="personal", name="Личное пространство"
    ).on_conflict_do_nothing(index_elements=[Organization.personal_user_id]).returning(Organization.id))
    if new_id is not None:
        db.add(Membership(org_id=new_id, user_id=user_id, role="owner"))
        await db.flush()
        return new_id
    row = (await db.execute(_active(user_id).where(Organization.personal_user_id == user_id))).one_or_none()
    if row is None:
        raise TenantNotFound()
    return row.id
