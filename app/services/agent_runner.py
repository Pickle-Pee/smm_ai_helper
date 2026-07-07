from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from app.agents import (
    AnalyticsAgent,
    ContentAgent,
    PromoAgent,
    StrategyAgent,
    TrendsAgent,
)
from app.presenters import format_agent_result

# Храним классы, а не singleton-экземпляры, чтобы не ловить гонки при параллельных запросах.
AGENT_MAP: Dict[str, Type] = {
    "strategy": StrategyAgent,
    "content": ContentAgent,
    "analytics": AnalyticsAgent,
    "promo": PromoAgent,
    "trends": TrendsAgent,
}


class AgentRunner:
    """Creates and runs task agents with runtime model/token overrides."""

    async def run(
        self,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any],
        model: str,
        max_output_tokens: int,
        qc_issues: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        agent_cls = AGENT_MAP.get(agent_type)
        if not agent_cls:
            raise ValueError("Unknown agent type")

        agent = agent_cls()

        brief = {"task_description": task_description, **(answers or {})}
        if qc_issues:
            brief["qc_issues"] = qc_issues

        kwargs: Dict[str, Any] = {}
        if agent_type == "content":
            period = answers.get("period") or answers.get("days")
            if period:
                try:
                    kwargs["days"] = int(period)
                except Exception:
                    pass

        agent.model_override = model
        agent.max_output_tokens_override = max_output_tokens

        result = await agent.run(brief, **kwargs)
        content = format_agent_result(agent_type, result)

        return {
            "content": content,
            "format": "markdown",
            "assumptions": result.get("assumptions") or [],
            "confidence": result.get("confidence") or "medium",
            "warnings": result.get("warnings") or [],
        }
