# app/routers/tasks.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db import get_session
from app.models import Task, User
from app.schemas import TaskRead, TaskShort

router = APIRouter(prefix="/tasks", tags=["tasks"])


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
