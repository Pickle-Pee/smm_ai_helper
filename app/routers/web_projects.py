from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import web_project_dto as dto
from app.db import get_session
from app.services import organizations, project_onboarding
from app.services import web_projects as service
from app.web_security import WebFailure, WebPrincipal, require_web_session

router = APIRouter(prefix="/v2", tags=["projects"])
DB = Annotated[AsyncSession, Depends(get_session)]
Principal = Annotated[WebPrincipal, Depends(require_web_session)]


@router.get("/orgs")
async def orgs(db: DB, principal: Principal) -> dto.OrgList:
    result = dto.OrgList(items=await organizations.active_memberships(db, principal.user_id))
    await db.commit()
    return result


@router.get("/orgs/{org_id}/projects")
async def list_projects(org_id: UUID, db: DB, principal: Principal, limit: int = Query(20, ge=1, le=50),
                        cursor: str | None = Query(None, max_length=512, pattern=r"^[A-Za-z0-9_-]+$"),
                        status: dto.Status | None = None) -> dto.ProjectList:
    org = await service.access(db, principal.user_id, org_id, "viewer")
    result = await service.page(db, principal.user_id, org, limit, cursor, status)
    await db.commit()
    return result


@router.post("/orgs/{org_id}/projects", status_code=201, responses={200: {"model": dto.Project}})
async def create_project(org_id: UUID, body: dto.ProjectCreate, response: Response, db: DB, principal: Principal,
                         idempotency_key: UUID | None = Header(None)) -> dto.Project:
    org = await service.access(db, principal.user_id, org_id, "editor")
    project, brand, created = await service.create(db, principal.user_id, org, body, idempotency_key)
    result = await service.view(db, principal.user_id, org, project, brand)
    await db.commit()
    response.status_code = 201 if created else 200
    return result


@router.get("/projects/{project_id}")
async def get_project(project_id: UUID, db: DB, principal: Principal) -> dto.Project:
    rows = await service.one(db, principal.user_id, project_id, "viewer")
    result = await service.view(db, principal.user_id, *rows)
    await db.commit()
    return result


def check_version(row, expected):
    if row.version != expected:
        raise WebFailure(409, "stale_project")


@router.patch("/projects/{project_id}")
async def patch_project(project_id: UUID, body: dto.ProjectPatch, db: DB, principal: Principal) -> dto.Project:
    org, project, brand = await service.one(db, principal.user_id, project_id, "editor")
    check_version(project, body.expected_version)
    for key, value in body.model_dump(exclude_unset=True, exclude={"expected_version"}).items():
        setattr(project, key, value)
    project.version += 1
    project.updated_at = datetime.now(timezone.utc)
    result = await service.view(db, principal.user_id, org, project, brand)
    await db.commit()
    return result


@router.get("/projects/{project_id}/brand")
async def get_brand(project_id: UUID, db: DB, principal: Principal) -> dto.Brand:
    _, _, brand = await service.one(db, principal.user_id, project_id, "viewer")
    result = await service.brand_view(db, principal.user_id, brand)
    await db.commit()
    return result


async def finish_brand(db, uid, project, brand):
    brand.updated_at = project.updated_at = datetime.now(timezone.utc)
    brand.updated_by = uid
    brand.version += 1
    result = await service.brand_view(db, uid, brand)
    await db.commit()
    return result


@router.patch("/projects/{project_id}/brand")
async def patch_brand(project_id: UUID, body: dto.BrandPatch, db: DB, principal: Principal) -> dto.Brand:
    _, project, brand = await service.one(db, principal.user_id, project_id, "editor")
    check_version(brand, body.expected_version)
    service.apply_fields(brand, body)
    return await finish_brand(db, principal.user_id, project, brand)


@router.post("/projects/{project_id}/brand/import-telegram")
async def import_brand(project_id: UUID, body: dto.BrandImport, db: DB, principal: Principal) -> dto.Brand:
    org, project, brand = await service.one(db, principal.user_id, project_id, "owner")
    if org.kind != "personal":
        raise WebFailure(403, "forbidden")
    check_version(brand, body.expected_version)
    try:
        await project_onboarding.import_personal_brand(db, principal.user_id, brand)
    except project_onboarding.ImportUnavailable as exc:
        raise WebFailure(403 if exc.code == "feature_disabled" else 409, exc.code) from None
    return await finish_brand(db, principal.user_id, project, brand)
