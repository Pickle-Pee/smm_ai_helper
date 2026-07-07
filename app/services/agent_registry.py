from __future__ import annotations

from typing import Type

from app.agents import (
    AnalyticsAgent,
    ContentAgent,
    PromoAgent,
    StrategyAgent,
    TrendsAgent,
)


class AgentRegistry:
    """Central registry for supported task agents and their routing metadata."""

    _AGENT_MAP: dict[str, Type] = {
        "strategy": StrategyAgent,
        "content": ContentAgent,
        "analytics": AnalyticsAgent,
        "promo": PromoAgent,
        "trends": TrendsAgent,
    }
    _HARD_AGENT_TYPES: set[str] = {"strategy", "analytics"}

    @classmethod
    def supported_agent_types(cls) -> set[str]:
        return set(cls._AGENT_MAP.keys())

    @classmethod
    def is_supported(cls, agent_type: str) -> bool:
        return agent_type in cls._AGENT_MAP

    @classmethod
    def is_hard(cls, agent_type: str) -> bool:
        return agent_type in cls._HARD_AGENT_TYPES

    @classmethod
    def get_agent_class(cls, agent_type: str) -> Type | None:
        return cls._AGENT_MAP.get(agent_type)
