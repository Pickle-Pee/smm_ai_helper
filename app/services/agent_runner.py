from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.agent_input_builder import AgentInputBuilder
from app.services.agent_output_builder import AgentOutputBuilder
from app.services.agent_registry import AgentRegistry


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
        agent_cls = AgentRegistry.get_agent_class(agent_type)
        if not agent_cls:
            raise ValueError("Unknown agent type")

        agent_input = AgentInputBuilder.build(
            agent_type=agent_type,
            task_description=task_description,
            answers=answers,
            qc_issues=qc_issues,
        )

        agent = agent_cls()
        agent.model_override = model
        agent.max_output_tokens_override = max_output_tokens

        raw_result = await agent.run(agent_input.brief, **agent_input.kwargs)
        return AgentOutputBuilder.build(agent_type, raw_result)
