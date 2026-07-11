import asyncio
from types import SimpleNamespace

import pytest

from app.models import BrandProfile
from app.services.brand_profile_service import BrandProfileService
from app.services.user_service import UserService


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeExecuteResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDbSession:
    def __init__(self, execute_value=None):
        self.execute_value = execute_value
        self.executed = []
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return FakeExecuteResult(self.execute_value)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def refresh(self, item):
        self.refreshed.append(item)


def test_get_by_user_id_returns_profile():
    profile = BrandProfile(user_id=42, brand_name="Brand")
    db_session = FakeDbSession(execute_value=profile)

    result = asyncio.run(
        BrandProfileService.get_by_user_id(db_session, user_id=42)
    )

    assert result is profile
    assert len(db_session.executed) == 1


def test_get_by_telegram_id_returns_none_when_user_missing(monkeypatch):
    async def fake_get_by_telegram_id(_session, telegram_id):
        assert telegram_id == 12345
        return None

    monkeypatch.setattr(
        UserService,
        "get_by_telegram_id",
        staticmethod(fake_get_by_telegram_id),
    )

    result = asyncio.run(
        BrandProfileService.get_by_telegram_id(
            FakeDbSession(),
            telegram_id=12345,
        )
    )

    assert result is None


def test_get_by_telegram_id_resolves_profile(monkeypatch):
    db_session = FakeDbSession()
    profile = BrandProfile(user_id=77, brand_name="Brand")

    async def fake_get_by_telegram_id(_session, telegram_id):
        assert _session is db_session
        assert telegram_id == 12345
        return SimpleNamespace(id=77)

    async def fake_get_by_user_id(_session, user_id):
        assert _session is db_session
        assert user_id == 77
        return profile

    monkeypatch.setattr(
        UserService,
        "get_by_telegram_id",
        staticmethod(fake_get_by_telegram_id),
    )
    monkeypatch.setattr(
        BrandProfileService,
        "get_by_user_id",
        staticmethod(fake_get_by_user_id),
    )

    result = asyncio.run(
        BrandProfileService.get_by_telegram_id(
            db_session,
            telegram_id=12345,
        )
    )

    assert result is profile


def test_upsert_for_user_creates_and_normalizes_profile(monkeypatch):
    db_session = FakeDbSession()

    async def fake_get_by_user_id(_session, user_id):
        assert _session is db_session
        assert user_id == 42
        return None

    monkeypatch.setattr(
        BrandProfileService,
        "get_by_user_id",
        staticmethod(fake_get_by_user_id),
    )

    profile = asyncio.run(
        BrandProfileService.upsert_for_user(
            db_session,
            user_id=42,
            values={
                "brand_name": "Brand",
                "product_description": "Marketing product",
                "audience": "Experts",
                "tone": "Human",
                "goals": "Growth",
                "channels": ("Telegram", "VK"),
                "extra_json": {"positioning": "Marketing copilot"},
            },
        )
    )

    assert db_session.added == [profile]
    assert db_session.commits == 1
    assert db_session.refreshed == [profile]
    assert profile.user_id == 42
    assert profile.brand_name == "Brand"
    assert profile.product_description == "Marketing product"
    assert profile.audience == "Experts"
    assert profile.tone == "Human"
    assert profile.goals == ["Growth"]
    assert profile.channels == ["Telegram", "VK"]
    assert profile.extra_json == {"positioning": "Marketing copilot"}
    assert profile.updated_at is not None


def test_upsert_for_user_updates_only_provided_fields(monkeypatch):
    db_session = FakeDbSession()
    profile = BrandProfile(
        user_id=42,
        brand_name="Existing Brand",
        audience="Old audience",
        goals=["Awareness"],
        extra_json={"positioning": "Old", "offer": "Audit"},
    )

    async def fake_get_by_user_id(_session, user_id):
        assert _session is db_session
        assert user_id == 42
        return profile

    monkeypatch.setattr(
        BrandProfileService,
        "get_by_user_id",
        staticmethod(fake_get_by_user_id),
    )

    result = asyncio.run(
        BrandProfileService.upsert_for_user(
            db_session,
            user_id=42,
            values={
                "audience": "New audience",
                "goals": ["Sales", "Retention"],
                "extra_json": {
                    "positioning": "New",
                    "competitors": ["A", "B"],
                },
            },
        )
    )

    assert result is profile
    assert db_session.added == []
    assert db_session.commits == 1
    assert profile.brand_name == "Existing Brand"
    assert profile.audience == "New audience"
    assert profile.goals == ["Sales", "Retention"]
    assert profile.extra_json == {
        "positioning": "New",
        "offer": "Audit",
        "competitors": ["A", "B"],
    }


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"unknown": "value"}, "Unknown brand profile fields"),
        ({"goals": {"bad": "shape"}}, "goals must be"),
        ({"extra_json": ["bad"]}, "extra_json must be"),
    ],
)
def test_upsert_validates_before_touching_session(values, error):
    db_session = FakeDbSession()

    with pytest.raises(ValueError, match=error):
        asyncio.run(
            BrandProfileService.upsert_for_user(
                db_session,
                user_id=42,
                values=values,
            )
        )

    assert db_session.executed == []
    assert db_session.added == []
    assert db_session.commits == 0


def test_to_context_merges_extra_and_core_fields():
    profile = BrandProfile(
        user_id=42,
        brand_name="Brand",
        audience="Experts",
        goals=["Growth"],
        extra_json={
            "positioning": "Marketing copilot",
            "brand_name": "Should be overridden",
        },
    )

    assert BrandProfileService.to_context(profile) == {
        "positioning": "Marketing copilot",
        "brand_name": "Brand",
        "audience": "Experts",
        "goals": ["Growth"],
    }
    assert BrandProfileService.to_context(None) == {}
