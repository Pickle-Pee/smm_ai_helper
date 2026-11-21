"""The persisted readiness predicate shared by onboarding and Telegram admission."""
from app.models import BrandProfile


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
