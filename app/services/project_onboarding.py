"""Initialize the personal project brand in the browser exchange transaction."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExternalIdentity, ProjectBrand
from app.services import organizations, projects
from app.services.brand_profile_service import BrandProfileService


class ImportUnavailable(Exception):
    def __init__(self, code: str):
        self.code = code


EXTRA_LIMITS = {
    "industry": 200, "usp": 4000, "customer_job_or_need": 4000, "relevant_alternative": 4000,
    "product_truth": 4000, "existing_proof": 4000, "geography": 4000, "economics": 4000,
}


def strings(value, count, length):
    if not isinstance(value, list):
        return []
    return [item[:length] for item in value if isinstance(item, str) and item.strip()][:count]


async def import_personal_brand(db: AsyncSession, user_id: int, brand: ProjectBrand):
    org = await projects.authorized_org(db, user_id, brand.org_id, "owner")
    if org.kind != "personal":
        raise organizations.InsufficientRole()
    if brand.imported_at is not None:
        raise ImportUnavailable("feature_disabled")
    verified = await db.scalar(select(ExternalIdentity.id).where(
        ExternalIdentity.user_id == user_id, ExternalIdentity.provider == "telegram",
        ExternalIdentity.verified_at.is_not(None)))
    if verified is None:
        raise ImportUnavailable("telegram_identity_required")
    source = await BrandProfileService.get_by_user_id(db, user_id)
    if source is None:
        raise ImportUnavailable("import_source_missing")
    brand.brand_name = source.brand_name
    for field in ("product_description", "audience", "tone"):
        value = getattr(source, field)
        setattr(brand, field, value[:4000] if value is not None else None)
    brand.goals = strings(source.goals, 10, 300)
    brand.channels = strings(source.channels, 20, 100)
    extra = source.extra_json if isinstance(source.extra_json, dict) else {}
    brand.extra_json = {key: extra[key][:limit] for key, limit in EXTRA_LIMITS.items()
                        if isinstance(extra.get(key), str)}
    if isinstance(extra.get("competitors"), list):
        brand.extra_json["competitors"] = strings(extra["competitors"], 10, 300)
    brand.source_profile_id = source.id
    brand.imported_at = datetime.now(timezone.utc)
    brand.imported_by = brand.updated_by = user_id


async def initialize(db: AsyncSession, user_id: int):
    org_id = await organizations.ensure_personal(db, user_id)
    project = await projects.ensure_default(db, user_id, org_id)
    # An existing row records completed initialization, including an empty brand.
    if await db.get(ProjectBrand, project.id) is not None:
        return
    brand = ProjectBrand(project_id=project.id, org_id=org_id)
    try:
        await import_personal_brand(db, user_id, brand)
    except ImportUnavailable as exc:
        if exc.code not in {"telegram_identity_required", "import_source_missing"}:
            raise
    db.add(brand)
    await db.flush()
