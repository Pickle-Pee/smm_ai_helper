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


async def next_step(db, user_id: int | None) -> str:
    if user_id is None or await db.get(UserPreferredName, user_id) is None:
        return "name"
    profile = await BrandProfileService.get_by_user_id(db, user_id)
    return next(iter(missing_brand_steps(profile)), "ready")


async def current_step(db, actor: int) -> str:
    user_id = await IdentityService.resolve_telegram_user_id(db, actor)
    return await next_step(db, user_id)
