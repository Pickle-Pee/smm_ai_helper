# app/routers/tasks.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db import get_session
from app.models import Task
from app.schemas import (
    TaskRead,
    TaskShort,
    TaskStartRequest,
    TaskAnswerRequest,
    TaskNeedInfoResponse,
    TaskDoneResponse,
)
from app.services.orchestrator import OrchestratorService
from app.services.user_service import UserService

router = APIRouter(prefix="/tasks", tags=["tasks"])
orchestrator = OrchestratorService()


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/by_user/{telegram_id}", response_model=list[TaskShort])
async def get_tasks_by_user(
    telegram_id: int,
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """
    История задач по конкретному юзеру (по telegram_id), последние N.
    """
    user = await UserService.get_by_telegram_id(session, telegram_id)
    if not user:
        return []

    tasks_result = await session.execute(
        select(Task)
        .where(Task.user_id == user.id)
        .order_by(desc(Task.created_at))
        .limit(limit)
    )
    tasks = tasks_result.scalars().all()
    return tasks


@router.post("/start", response_model=TaskNeedInfoResponse | TaskDoneResponse)
async def start_task(
    payload: TaskStartRequest,
    session: AsyncSession = Depends(get_session),
):
    if payload.agent_type not in {"strategy", "content", "analytics", "promo", "trends"}:
        raise HTTPException(status_code=404, detail="Unknown agent type")

    user = await UserService.get_or_create(session, payload.user)
    response = await orchestrator.start_task(
        db_session=session,
        agent_type=payload.agent_type,
        task_description=payload.task_description,
        answers=payload.answers or {},
        mode=payload.mode,
        request_id=uuid.uuid4().hex,
        user_id=str(payload.user.telegram_id) if payload.user else "anonymous",
    )

    if response["status"] == "done":
        task = Task(
            user_id=user.id if user else None,
            agent_type=payload.agent_type,
            task_description=payload.task_description,
            answers=payload.answers,
            result=response["result"],
            status="done",
        )
        session.add(task)
        await session.commit()

    return response


@router.post("/answer", response_model=TaskNeedInfoResponse | TaskDoneResponse)
async def answer_task(
    payload: TaskAnswerRequest,
    session: AsyncSession = Depends(get_session),
):
    session_data = await orchestrator.get_session(session, payload.session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Unknown session")

    response = await orchestrator.answer(
        db_session=session,
        session_id=payload.session_id,
        key=payload.key,
        value=payload.value,
    )

    if response["status"] == "done":
        session_data.answers[payload.key] = payload.value

        user = None
        if session_data.user_id != "anonymous":
            user = await UserService.get_by_telegram_id(
                session,
                int(session_data.user_id),
            )

        task = Task(
            user_id=user.id if user else None,
            agent_type=session_data.agent_type,
            task_description=session_data.task_description,
            answers=session_data.answers,
            result=response["result"],
            status="done",
        )
        session.add(task)
        await session.commit()

    return response
