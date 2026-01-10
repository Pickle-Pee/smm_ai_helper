# app/routers/tasks.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db import get_session
from app.models import Task, User
from app.schemas import (
    TaskRead,
    TaskShort,
    TaskStartRequest,
    TaskAnswerRequest,
    TaskNeedInfoResponse,
    TaskDoneResponse,
    UserCreate,
)
from app.services.orchestrator import OrchestratorService

router = APIRouter(prefix="/tasks", tags=["tasks"])
orchestrator = OrchestratorService()


async def get_or_create_user(session: AsyncSession, user_data: UserCreate | None) -> User | None:
    if user_data is None:
        return None

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
    # находим пользователя
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
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

    user = await get_or_create_user(session, payload.user)
    response = await orchestrator.start_task(
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
    session_data = orchestrator.get_session(payload.session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Unknown session")

    response = await orchestrator.answer(
        session_id=payload.session_id,
        key=payload.key,
        value=payload.value,
    )

    if response["status"] == "done":
        user = None
        if session_data.user_id != "anonymous":
            result = await session.execute(
                select(User).where(User.telegram_id == int(session_data.user_id))
            )
            user = result.scalar_one_or_none()

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
