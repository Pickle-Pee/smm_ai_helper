from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BrandProfile
from app.services.user_service import UserService


class BrandProfileService:
    """Persistence and context helpers for a user's stable brand profile."""

    CORE_FIELDS = {
        "brand_name",
        "product_description",
        "audience",
        "tone",
        "goals",
        "channels",
        "extra_json",
    }
    COLLECTION_FIELDS = {"goals", "channels"}

    @staticmethod
    async def get_by_user_id(
        session: AsyncSession,
        user_id: int,
    ) -> BrandProfile | None:
        result = await session.execute(
            select(BrandProfile).where(BrandProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_telegram_id(
        cls,
        session: AsyncSession,
        telegram_id: int,
    ) -> BrandProfile | None:
        user = await UserService.get_by_telegram_id(session, telegram_id)
        if user is None:
            return None
        return await cls.get_by_user_id(session, user.id)

    @classmethod
    async def get_context_for_chat_user(
        cls,
        session: AsyncSession,
        chat_user_id: str,
    ) -> Dict[str, Any]:
        """Resolve stable brand context for Telegram chat user IDs."""
        telegram_id = cls._resolve_telegram_id(chat_user_id)
        if telegram_id is None:
            return {}

        profile = await cls.get_by_telegram_id(session, telegram_id)
        return cls.to_context(profile)

    @staticmethod
    def _resolve_telegram_id(chat_user_id: str) -> int | None:
        normalized_user_id = (chat_user_id or "").strip()
        if normalized_user_id.lower().startswith("tg:"):
            normalized_user_id = normalized_user_id[3:].strip()

        if not normalized_user_id.isdigit():
            return None
        return int(normalized_user_id)

    @classmethod
    async def upsert_for_user(
        cls,
        session: AsyncSession,
        user_id: int,
        values: Dict[str, Any],
    ) -> BrandProfile:
        normalized_values = cls._validate_and_normalize(values)

        profile = await cls.get_by_user_id(session, user_id)
        if profile is None:
            profile = BrandProfile(user_id=user_id)
            session.add(profile)

        for field in cls.CORE_FIELDS - cls.COLLECTION_FIELDS - {"extra_json"}:
            if field in normalized_values:
                setattr(profile, field, normalized_values[field])

        for field in cls.COLLECTION_FIELDS:
            if field in normalized_values:
                setattr(profile, field, normalized_values[field])

        if "extra_json" in normalized_values:
            profile.extra_json = cls._merge_extra_json(
                current=profile.extra_json,
                incoming=normalized_values["extra_json"],
            )

        profile.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(profile)
        return profile

    @staticmethod
    def to_context(profile: BrandProfile | None) -> Dict[str, Any]:
        if profile is None:
            return {}

        context = dict(profile.extra_json or {})
        for field in (
            "brand_name",
            "product_description",
            "audience",
            "tone",
            "goals",
            "channels",
        ):
            value = getattr(profile, field)
            if value is not None:
                context[field] = value
        return context

    @classmethod
    def merge_context(
        cls,
        profile_context: Dict[str, Any] | None,
        chat_facts: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        """Overlay non-empty chat facts on top of the stable brand profile."""
        merged = dict(profile_context or {})
        for key, value in (chat_facts or {}).items():
            if cls._has_context_value(value):
                merged[key] = value
        return merged

    @staticmethod
    def _has_context_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    @classmethod
    def _validate_and_normalize(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        unknown_fields = set(values) - cls.CORE_FIELDS
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown brand profile fields: {fields}")

        normalized = dict(values)
        for field in cls.COLLECTION_FIELDS:
            if field in normalized:
                normalized[field] = cls._normalize_collection(
                    normalized[field],
                    field,
                )

        if "extra_json" in normalized:
            incoming = normalized["extra_json"]
            if incoming is not None and not isinstance(incoming, dict):
                raise ValueError("extra_json must be an object or null")

        return normalized

    @staticmethod
    def _normalize_collection(value: Any, field: str) -> list[Any] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple)):
            return list(value)
        raise ValueError(f"{field} must be a string, list, tuple, or null")

    @staticmethod
    def _merge_extra_json(
        current: Any,
        incoming: Any,
    ) -> Dict[str, Any] | None:
        if incoming is None:
            return None

        merged = dict(current or {})
        merged.update(incoming)
        return merged
