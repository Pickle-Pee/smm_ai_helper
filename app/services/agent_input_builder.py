from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AgentInput:
    brief: Dict[str, Any]
    kwargs: Dict[str, Any] = field(default_factory=dict)


class AgentInputBuilder:
    """Builds agent-specific input payloads from generic task data."""

    @classmethod
    def build(
        cls,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any],
        qc_issues: Optional[List[str]] = None,
    ) -> AgentInput:
        brief = cls._build_brief(
            task_description=task_description,
            answers=answers,
            qc_issues=qc_issues,
        )
        kwargs = cls._build_kwargs(
            agent_type=agent_type,
            answers=answers,
        )
        return AgentInput(brief=brief, kwargs=kwargs)

    @staticmethod
    def _build_brief(
        task_description: str,
        answers: Dict[str, Any],
        qc_issues: Optional[List[str]],
    ) -> Dict[str, Any]:
        brief = {"task_description": task_description, **(answers or {})}
        if qc_issues:
            brief["qc_issues"] = qc_issues
        return brief

    @classmethod
    def _build_kwargs(
        cls,
        agent_type: str,
        answers: Dict[str, Any],
    ) -> Dict[str, Any]:
        if agent_type == "content":
            return cls._build_content_kwargs(answers)
        return {}

    @staticmethod
    def _build_content_kwargs(answers: Dict[str, Any]) -> Dict[str, Any]:
        period = answers.get("period") or answers.get("days")
        if not period:
            return {}

        try:
            return {"days": int(period)}
        except Exception:
            return {}
