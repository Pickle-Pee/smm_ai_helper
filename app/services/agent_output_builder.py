from __future__ import annotations

from typing import Any, Dict

from app.presenters import format_agent_result


class AgentOutputBuilder:
    """Builds normalized task output from raw agent result."""

    @staticmethod
    def build(
        agent_type: str,
        raw_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "content": format_agent_result(agent_type, raw_result),
            "format": "markdown",
            "assumptions": raw_result.get("assumptions") or [],
            "confidence": raw_result.get("confidence") or "medium",
            "warnings": raw_result.get("warnings") or [],
        }
