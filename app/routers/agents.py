from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import AgentRunRequest, AgentRunResponse
from app.services.agent_registry import AgentRegistry
from app.services.agent_runner import AgentRunner
from app.services.task_result_service import TaskResultService
from app.services.task_router import TaskRouter
from app.services.user_service import UserService

router = APIRouter(prefix="/agents", tags=["agents"])
agent_runner = AgentRunner()
task_router = TaskRouter()


def _normalize_legacy_answers(answers: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve legacy direct-agent request compatibility."""
    normalized = dict(answers or {})
    if "channels" in normalized and isinstance(normalized["channels"], str):
        normalized["channels"] = [
            channel.strip()
            for channel in normalized["channels"].split(",")
            if channel.strip()
        ]
    return normalized


@router.post("/{agent_type}/run", response_model=AgentRunResponse, deprecated=True)
async def run_agent(
    agent_type: str,
    payload: AgentRunRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Legacy direct agent endpoint.

    New product flows should use /tasks/start and /tasks/answer so routing,
    clarification, QC, history, and future billing/learning hooks stay in one pipeline.
    """
    if not AgentRegistry.is_supported(agent_type):
        raise HTTPException(status_code=404, detail="Unknown agent type")

    user = await UserService.get_or_create(session, payload.user)
    user_id = user.id if user else None
    run_answers = _normalize_legacy_answers(payload.answers)
    decision = task_router.fallback_decision(agent_type)

    try:
        result_data = await agent_runner.run(
            agent_type=agent_type,
            task_description=payload.task_description,
            answers=run_answers,
            model=decision["model"],
            max_output_tokens=int(decision["max_output_tokens"]),
        )
        task = await TaskResultService.save_done_task(
            db_session=session,
            user_id=user_id,
            agent_type=agent_type,
            task_description=payload.task_description,
            answers=payload.answers,
            result=result_data,
        )
        return AgentRunResponse(
            task_id=task.id,
            agent_type=agent_type,
            status=task.status,
            result=result_data,
        )
    except Exception as e:
        await TaskResultService.save_error_task(
            db_session=session,
            user_id=user_id,
            agent_type=agent_type,
            task_description=payload.task_description,
            answers=payload.answers,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Agent execution failed")
