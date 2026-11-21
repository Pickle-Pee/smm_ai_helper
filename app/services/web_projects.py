import base64
import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from app import web_project_dto as dto
from app.models import Organization, Project, ProjectBrand, User
from app.services import organizations, projects
from app.web_security import WebFailure


async def access(db, uid, org_id, minimum):
    try:
        return await projects.authorized_org(db, uid, org_id, minimum)
    except organizations.TenantNotFound:
        raise WebFailure(404, "not_found") from None
    except organizations.InsufficientRole:
        raise WebFailure(403, "forbidden") from None


async def one(db, uid, project_id, minimum):
    org_id = await db.scalar(organizations.active_query(uid).with_only_columns(Organization.id)
                             .join(Project, Project.org_id == Organization.id).where(Project.id == project_id))
    if org_id is None:
        raise WebFailure(404, "not_found")
    org = await access(db, uid, org_id, minimum)
    row = (await db.execute(select(Project, ProjectBrand).join(ProjectBrand).where(
        Project.id == project_id, Project.org_id == org.id))).one_or_none()
    if row is None:
        raise WebFailure(404, "not_found")
    return org, row.Project, row.ProjectBrand


async def reference(db, user_id, viewer):
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    return dto.UserRef(id=user.id, display_name=user.first_name or user.username or None, is_self=user.id == viewer)


async def brand_view(db, uid, brand):
    source = None
    if brand.imported_at:
        source = dto.Provenance(imported_at=brand.imported_at, imported_by=await reference(db, brand.imported_by, uid))
    return dto.Brand(project_id=brand.project_id, version=brand.version, brand_name=brand.brand_name,
                     product_description=brand.product_description, audience=brand.audience, tone=brand.tone,
                     goals=brand.goals, channels=brand.channels, extra=brand.extra_json, imported_from=source,
                     updated_at=brand.updated_at, updated_by=await reference(db, brand.updated_by, uid))


async def view(db, uid, org, project, brand):
    edit = org.role in ("owner", "editor")
    permissions = dto.Permissions(can_edit=edit, can_submit=edit,
                                  can_import_telegram_brand=org.kind == "personal" and org.role == "owner"
                                  and brand.imported_at is None)
    return dto.Project(id=project.id, org_id=org.id, name=project.name, status=project.status, color=project.color,
                       version=project.version, role=org.role, permissions=permissions,
                       created_by=await reference(db, project.created_by, uid), created_at=project.created_at,
                       updated_at=project.updated_at, brand=await brand_view(db, uid, brand))


def apply_fields(brand, body):
    fields = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if "extra" in fields:
        merged = dict(brand.extra_json or {})
        for key, value in fields.pop("extra").items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        brand.extra_json = merged
    for key, value in fields.items():
        setattr(brand, key, [] if key in ("goals", "channels") and value is None else value)


async def create(db, uid, org, body, key):
    values = dict(id=uuid4(), org_id=org.id, created_by=uid, name=body.name, status=body.status, color=body.color)
    digest = hashlib.sha256(json.dumps([str(org.id), body.model_dump(mode="json", exclude_unset=True)],
                                       sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    stmt = insert(Project).values(**values, request_key=key, request_hash=digest if key else None)
    project = await db.scalar(stmt.on_conflict_do_nothing(index_elements=[Project.created_by, Project.request_key])
                              .returning(Project))
    if project is None:
        project = await db.scalar(select(Project).where(Project.org_id == org.id, Project.created_by == uid,
                                                        Project.request_key == key))
        if project is None or project.request_hash != digest:
            raise WebFailure(409, "idempotency_conflict")
        return project, await db.get(ProjectBrand, project.id), False
    brand = ProjectBrand(project_id=project.id, org_id=org.id, updated_by=uid)
    apply_fields(brand, body.brand)
    db.add(brand)
    await db.flush()
    return project, brand, True


async def page(db, uid, org, limit, cursor, status):
    query = select(Project, ProjectBrand).join(ProjectBrand).where(Project.org_id == org.id)
    if status:
        query = query.where(Project.status == status)
    if cursor:
        try:
            stamp, ident = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode().split("|")
            when, project_id = datetime.fromisoformat(stamp), UUID(ident)
            if when.tzinfo is None:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise WebFailure(422, "invalid_request") from None
        query = query.where(or_(Project.updated_at < when, and_(Project.updated_at == when, Project.id > project_id)))
    rows = (await db.execute(query.order_by(Project.updated_at.desc(), Project.id).limit(limit + 1))).all()
    items = [await view(db, uid, org, p, b) for p, b in rows[:limit]]
    following = None
    if len(rows) > limit:
        last = items[-1]
        following = base64.urlsafe_b64encode(f"{last.updated_at.isoformat()}|{last.id}".encode()).decode().rstrip("=")
    return dto.ProjectList(items=items, next_cursor=following)
