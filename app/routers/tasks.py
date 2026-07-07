# app/routers/tasks.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import (
    TaskRead,
    TaskShort,
    TaskStartRequest,
    TaskAnswerRequest,
    TaskNeedInfoResponse,
    TaskDoneResponse,
)
from app.services.task_history_service import TaskHistoryService
from app.services.task_pipeline import TaskPipelineService
from app.services.task_result_service import TaskResultService
from app.services.user_service import UserService

router = APIRouter(prefix="/tasks", tags=["tasks"])
task_pipeline = TaskPipelineService()


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await TaskHistoryService.get_task(session, task_id)
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
    return await TaskHistoryService.get_recent_tasks_by_telegram_id(
        db_session=session,
        telegram_id=telegram_id,
        limit=limit,
    )


@router.post("/start", response_model=TaskNeedInfoResponse | TaskDoneResponse)
async def start_task(
    payload: TaskStartRequest,
    session: AsyncSession = Depends(get_session),
):
    if payload.agent_type not in {"strategy", "content", "analytics", "promo", "trends"}:
        raise HTTPException(status_code=404, detail="Unknown agent type")

    user = await UserService.get_or_create(session, payload.user)
    response = await task_pipeline.start_task(
        db_session=session,
        agent_type=payload.agent_type,
        task_description=payload.task_description,
        answers=payload.answers or {},
        mode=payload.mode,
        request_id=uuid.uuid4().hex,
        user_id=str(payload.user.telegram_id) if payload.user else "anonymous",
    )

    if response["status"] == "done":
        await TaskResultService.save_done_task(
            db_session=session,
            user_id=user.id if user else None,
            agent_type=payload.agent_type,
            task_description=payload.task_description,
            answers=payload.answers,
            result=response["result"],
        )

    return response


@router.post("/answer", response_model=TaskNeedInfoResponse | TaskDoneResponse)
async def answer_task(
    payload: TaskAnswerRequest,
    session: AsyncSession = Depends(get_session),
):
    session_data = await task_pipeline.get_session(session, payload.session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Unknown session")

    response = await task_pipeline.answer(
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

        await TaskResultService.save_done_task(
            db_session=session,
            user_id=user.id if user else None,
            agent_type=session_data.agent_type,
            task_description=session_data.task_description,
            answers=session_data.answers,
            result=response["result"],
        )

    return response
