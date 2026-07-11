import asyncio
from types import SimpleNamespace

from app.services.brand_profile_service import BrandProfileService


def test_get_context_for_chat_user_skips_non_numeric_ids(monkeypatch):
    async def unexpected_lookup(cls, session, telegram_id):
        raise AssertionError("Telegram lookup must not run for non-numeric chat IDs")

    monkeypatch.setattr(
        BrandProfileService,
        "get_by_telegram_id",
        classmethod(unexpected_lookup),
    )

    result = asyncio.run(
        BrandProfileService.get_context_for_chat_user(
            session=object(),
            chat_user_id="anonymous",
        )
    )

    assert result == {}


def test_get_context_for_chat_user_loads_numeric_telegram_profile(monkeypatch):
    db_session = object()
    profile = SimpleNamespace(
        brand_name="Brand",
        product_description="Product",
        audience="Experts",
        tone="Calm",
        goals=["Growth"],
        channels=["Telegram"],
        extra_json={"category": "education"},
    )
    calls = []

    async def fake_lookup(cls, session, telegram_id):
        calls.append(
            {
                "session": session,
                "telegram_id": telegram_id,
            }
        )
        return profile

    monkeypatch.setattr(
        BrandProfileService,
        "get_by_telegram_id",
        classmethod(fake_lookup),
    )

    result = asyncio.run(
        BrandProfileService.get_context_for_chat_user(
            session=db_session,
            chat_user_id=" 12345 ",
        )
    )

    assert calls == [
        {
            "session": db_session,
            "telegram_id": 12345,
        }
    ]
    assert result == {
        "category": "education",
        "brand_name": "Brand",
        "product_description": "Product",
        "audience": "Experts",
        "tone": "Calm",
        "goals": ["Growth"],
        "channels": ["Telegram"],
    }


def test_merge_context_overlays_only_non_empty_chat_facts():
    result = BrandProfileService.merge_context(
        profile_context={
            "brand_name": "Stable Brand",
            "audience": "Base audience",
            "tone": "Expert",
            "channels": ["Telegram"],
            "budget": 0,
        },
        chat_facts={
            "brand_name": "   ",
            "audience": "Current campaign audience",
            "tone": None,
            "channels": [],
            "campaign": "Summer",
            "budget": 100,
            "is_active": False,
        },
    )

    assert result == {
        "brand_name": "Stable Brand",
        "audience": "Current campaign audience",
        "tone": "Expert",
        "channels": ["Telegram"],
        "budget": 100,
        "campaign": "Summer",
        "is_active": False,
    }


def test_merge_context_does_not_mutate_inputs():
    profile_context = {"brand_name": "Brand"}
    chat_facts = {"audience": "Experts"}

    result = BrandProfileService.merge_context(profile_context, chat_facts)

    assert result == {
        "brand_name": "Brand",
        "audience": "Experts",
    }
    assert profile_context == {"brand_name": "Brand"}
    assert chat_facts == {"audience": "Experts"}
