"""Assemble Me for a verified users.id in the caller's transaction."""
from collections.abc import Awaitable, Callable
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import web_session_dto as dto
from app.models import ExternalIdentity, User, WebSession

Memberships = Callable[[AsyncSession, int, bool], Awaitable[list[dto.OrganizationMembership]]]


class OnboardingUnavailable(Exception):
    pass


async def memberships(db: AsyncSession, user_id: int, first_login: bool) -> list[dto.OrganizationMembership]:
    """B3/B4 supply active memberships and idempotent onboarding inside exchange."""
    raise OnboardingUnavailable()


async def project(db: AsyncSession, row: WebSession, reader: Memberships, *, login: bool) -> dto.Me:
    active = await reader(db, row.user_id, login)
    if not any(member.organization.kind == "personal" and member.role == "owner" for member in active):
        raise OnboardingUnavailable()
    user = await db.get(User, row.user_id)
    identities = await db.scalars(select(ExternalIdentity).where(
        ExternalIdentity.user_id == row.user_id).order_by(ExternalIdentity.id))
    return dto.Me(
        user=dto.User(id=user.id, display_name=user.first_name or user.username or None,
                      created_at=user.created_at.replace(tzinfo=timezone.utc)),
        identities=[dto.Identity(provider="oidc" if identity.provider.startswith("oidc:") else identity.provider,
                                 linked_at=identity.created_at) for identity in identities],
        memberships=active,
        session=dto.SessionInfo(issued_at=row.created_at, idle_expires_at=row.idle_expires_at,
                                absolute_expires_at=row.absolute_expires_at),
        features=dto.Features(),
    )
