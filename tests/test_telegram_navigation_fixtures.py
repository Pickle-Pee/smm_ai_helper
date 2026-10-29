"""Explicit baseline dependency for older isolated Telegram flow tests."""
from unittest.mock import AsyncMock

import pytest

from bot import project_navigation


@pytest.fixture
def no_selected_project(monkeypatch):
    # These suites exercise existing transport/FSM boundaries. Durable selection
    # itself is exercised with retained state in test_telegram_navigation.py.
    current = AsyncMock(return_value={"version": 0, "active": None})
    monkeypatch.setattr(project_navigation, "binding", current)
    return current
