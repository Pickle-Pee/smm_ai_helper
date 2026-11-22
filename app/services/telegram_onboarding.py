"""The persisted readiness predicate shared by onboarding and Telegram admission."""
from app.models import BrandProfile, UserPreferredName
from app.services.brand_profile_service import BrandProfileService
from app.services.identity_service import IdentityService


def missing_brand_steps(profile: BrandProfile | None) -> tuple[str, ...]:
    def has_text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    if profile is None:
        return ("product", "audience", "goal")
    goals = profile.goals
    checks = {
        "product": has_text(profile.product_description),
        "audience": has_text(profile.audience),
        "goal": isinstance(goals, list) and any(has_text(goal) for goal in goals),
    }
    return tuple(step for step, ready in checks.items() if not ready)


async def _progress(db, user_id: int | None) -> tuple[str, UserPreferredName | None]:
    name = await db.get(UserPreferredName, user_id) if user_id is not None else None
    if name is None:
        return "name", None
    profile = await BrandProfileService.get_by_user_id(db, user_id)
    return next(iter(missing_brand_steps(profile)), "ready"), name


async def next_step(db, user_id: int | None) -> str:
    step, _ = await _progress(db, user_id)
    return step


async def current_progress(db, actor: int) -> tuple[str, UserPreferredName | None]:
    user_id = await IdentityService.resolve_telegram_user_id(db, actor)
    return await _progress(db, user_id)
