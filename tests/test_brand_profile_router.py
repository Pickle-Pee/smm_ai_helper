import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.routers.brand_profile as brand_profile_router_module
from app.routers.brand_profile import get_brand_profile, patch_brand_profile
from app.schemas import BrandProfileRead, BrandProfileUpdate


def make_profile(**overrides):
    data = {
        "id": 10,
        "user_id": 7,
        "brand_name": "Brand",
        "product_description": "Product",
        "audience": "Experts",
        "tone": "Professional",
        "goals": ["Sales"],
        "channels": ["Telegram"],
        "extra_json": {"market": "B2B"},
        "created_at": datetime(2026, 7, 11, 10, 0, 0),
        "updated_at": datetime(2026, 7, 11, 11, 0, 0),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_get_brand_profile_returns_existing_profile(monkeypatch):
    db_session = object()
    profile = make_profile()

    async def fake_get_by_telegram_id(session, telegram_id):
        assert session is db_session
        assert telegram_id == 12345
        return profile

    monkeypatch.setattr(
        brand_profile_router_module.BrandProfileService,
        "get_by_telegram_id",
        fake_get_by_telegram_id,
    )

    result = asyncio.run(get_brand_profile(telegram_id=12345, session=db_session))

    assert result is profile
    validated = BrandProfileRead.model_validate(result)
    assert validated.brand_name == "Brand"
    assert validated.user_id == 7


def test_get_brand_profile_raises_404_when_missing(monkeypatch):
    async def fake_get_by_telegram_id(_session, _telegram_id):
        return None

    monkeypatch.setattr(
        brand_profile_router_module.BrandProfileService,
        "get_by_telegram_id",
        fake_get_by_telegram_id,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_brand_profile(telegram_id=12345, session=object()))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Brand profile not found"


def test_patch_brand_profile_upserts_only_explicit_fields(monkeypatch):
    db_session = object()
    profile = make_profile(brand_name="Updated Brand", tone=None)
    calls = []

    async def fake_get_user(session, telegram_id):
        assert session is db_session
        assert telegram_id == 12345
        return SimpleNamespace(id=7)

    async def fake_upsert_for_user(session, user_id, values):
        calls.append(
            {
                "session": session,
                "user_id": user_id,
                "values": values,
            }
        )
        return profile

    monkeypatch.setattr(
        brand_profile_router_module.UserService,
        "get_by_telegram_id",
        fake_get_user,
    )
    monkeypatch.setattr(
        brand_profile_router_module.BrandProfileService,
        "upsert_for_user",
        fake_upsert_for_user,
    )

    result = asyncio.run(
        patch_brand_profile(
            telegram_id=12345,
            payload=BrandProfileUpdate(
                brand_name="Updated Brand",
                tone=None,
                channels="Telegram",
            ),
            session=db_session,
        )
    )

    assert result is profile
    assert calls == [
        {
            "session": db_session,
            "user_id": 7,
            "values": {
                "brand_name": "Updated Brand",
                "tone": None,
                "channels": "Telegram",
            },
        }
    ]


def test_patch_brand_profile_raises_404_for_unknown_user(monkeypatch):
    async def fake_get_user(_session, _telegram_id):
        return None

    monkeypatch.setattr(
        brand_profile_router_module.UserService,
        "get_by_telegram_id",
        fake_get_user,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            patch_brand_profile(
                telegram_id=12345,
                payload=BrandProfileUpdate(brand_name="Brand"),
                session=object(),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"


def test_patch_brand_profile_rejects_empty_patch(monkeypatch):
    async def fake_get_user(_session, _telegram_id):
        return SimpleNamespace(id=7)

    monkeypatch.setattr(
        brand_profile_router_module.UserService,
        "get_by_telegram_id",
        fake_get_user,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            patch_brand_profile(
                telegram_id=12345,
                payload=BrandProfileUpdate(),
                session=object(),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "No fields to update"


def test_patch_brand_profile_converts_service_validation_to_422(monkeypatch):
    async def fake_get_user(_session, _telegram_id):
        return SimpleNamespace(id=7)

    async def fake_upsert_for_user(**_kwargs):
        raise ValueError("channels must be valid")

    monkeypatch.setattr(
        brand_profile_router_module.UserService,
        "get_by_telegram_id",
        fake_get_user,
    )
    monkeypatch.setattr(
        brand_profile_router_module.BrandProfileService,
        "upsert_for_user",
        fake_upsert_for_user,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            patch_brand_profile(
                telegram_id=12345,
                payload=BrandProfileUpdate(channels=["Telegram"]),
                session=object(),
            )
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "channels must be valid"


def test_brand_profile_update_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        BrandProfileUpdate(unknown_field="value")
