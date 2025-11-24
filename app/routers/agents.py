from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    StrategyAgent,
    ContentAgent,
    AnalyticsAgent,
    PromoAgent,
    TrendsAgent,
)
from app.db import get_session
from app.models import Task, User
from app.schemas import AgentRunRequest, AgentRunResponse, UserCreate

router = APIRouter(prefix="/agents", tags=["agents"])

AGENTS_MAP = {
    "strategy": StrategyAgent(),
    "content": ContentAgent(),
    "analytics": AnalyticsAgent(),
    "promo": PromoAgent(),
    "trends": TrendsAgent(),
}


async def get_or_create_user(session: AsyncSession, user_data: UserCreate | None) -> User | None:
    if user_data is None:
        return None

    from sqlalchemy import select

    result = await session.execute(
        select(User).where(User.telegram_id == user_data.telegram_id)
    )
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        telegram_id=user_data.telegram_id,
        username=user_data.username,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


@router.post("/{agent_type}/run", response_model=AgentRunResponse)
async def run_agent(
    agent_type: str,
    payload: AgentRunRequest,
    session: AsyncSession = Depends(get_session),
):
    if agent_type not in AGENTS_MAP:
        raise HTTPException(status_code=404, detail="Unknown agent type")

    agent = AGENTS_MAP[agent_type]

    user = await get_or_create_user(session, payload.user)
    user_id = user.id if user else None

    brief: Dict[str, Any] = {
        "task_description": payload.task_description,
        **payload.answers,
    }

    if "channels" in brief and isinstance(brief["channels"], str):
        brief["channels"] = [
            c.strip() for c in brief["channels"].split(",") if c.strip()
        ]

    try:
        result_data = await agent.run(brief)
        task = Task(
            user_id=user_id,
            agent_type=agent_type,
            task_description=payload.task_description,
            answers=payload.answers,
            result=result_data,
            status="done",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return AgentRunResponse(
            task_id=task.id,
            agent_type=agent_type,
            status=task.status,
            result=result_data,
        )
    except Exception as e:
        task = Task(
            user_id=user_id,
            agent_type=agent_type,
            task_description=payload.task_description,
            answers=payload.answers,
            result=None,
            status="error",
            error=str(e),
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        raise HTTPException(status_code=500, detail="Agent execution failed")
