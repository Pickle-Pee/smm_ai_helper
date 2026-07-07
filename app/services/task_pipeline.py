from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runner import AgentRunner
from app.services.clarification_service import ClarificationService
from app.services.qc_service import QCService
from app.services.task_image_service import TaskImageService
from app.services.task_router import TaskRouter
from app.services.task_session_service import TaskSessionService, TaskSessionState

logger = logging.getLogger(__name__)


class TaskPipelineService:
    """Coordinates the full multi-step task pipeline."""

    def __init__(self) -> None:
        self.task_router = TaskRouter()
        self.clarification_service = ClarificationService()
        self.agent_runner = AgentRunner()
        self.qc_service = QCService()
        self.task_image_service = TaskImageService()

    async def start_task(
        self,
        db_session: AsyncSession,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any],
        mode: str,
        request_id: str = "-",
        user_id: str = "anonymous",
    ) -> Dict[str, Any]:
        session_state = TaskSessionState(
            session_id=uuid.uuid4().hex,
            agent_type=agent_type,
            task_description=task_description,
            mode=mode,
            answers=answers or {},
            request_id=request_id,
            user_id=user_id,
        )
        await TaskSessionService.save(db_session, session_state)
        await db_session.commit()
        return await self._continue_session(db_session, session_state)

    async def answer(
        self,
        db_session: AsyncSession,
        session_id: str,
        key: str,
        value: str,
    ) -> Dict[str, Any]:
        session_state = await TaskSessionService.get(db_session, session_id)
        if not session_state:
            raise ValueError("Unknown session")

        session_state.answers[key] = value
        await TaskSessionService.save(db_session, session_state)
        await db_session.commit()
        return await self._continue_session(db_session, session_state)

    async def get_session(
        self,
        db_session: AsyncSession,
        session_id: str,
    ) -> Optional[TaskSessionState]:
        return await TaskSessionService.get(db_session, session_id)

    async def _continue_session(
        self,
        db_session: AsyncSession,
        session_state: TaskSessionState,
    ) -> Dict[str, Any]:
        decision, usage = await self.task_router.route(
            session_state.agent_type,
            session_state.task_description,
            session_state.answers,
        )

        clarification_response = await self._handle_clarification(
            db_session=db_session,
            session_state=session_state,
            decision=decision,
        )
        if clarification_response:
            return clarification_response

        result = await self._run_agent_with_qc(
            session_state=session_state,
            decision=decision,
        )

        return await self._finalize_session(
            db_session=db_session,
            session_state=session_state,
            result=result,
            usage=usage,
        )

    async def _handle_clarification(
        self,
        db_session: AsyncSession,
        session_state: TaskSessionState,
        decision: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        needs_clarification = decision.get("needs_clarification", False)
        max_questions = 6

        if not needs_clarification or session_state.questions_asked >= max_questions:
            return None

        remaining = max_questions - session_state.questions_asked
        next_questions = decision.get("next_questions") or []
        questions = next_questions if next_questions else await self.clarification_service.generate_questions(
            session_state.task_description,
            session_state.answers,
            remaining,
        )

        session_state.questions_asked += len(questions)
        await TaskSessionService.save(db_session, session_state)
        await db_session.commit()

        return {
            "status": "need_info",
            "session_id": session_state.session_id,
            "questions": questions[:3],
        }

    async def _run_agent_with_qc(
        self,
        session_state: TaskSessionState,
        decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        model = decision["model"]
        max_output_tokens = int(decision["max_output_tokens"])

        result = await self.agent_runner.run(
            agent_type=session_state.agent_type,
            task_description=session_state.task_description,
            answers=session_state.answers,
            model=model,
            max_output_tokens=max_output_tokens,
        )

        needs_qc = bool(decision.get("needs_qc", False)) or result.get("confidence") == "low"
        if not needs_qc:
            return result

        issues = await self.qc_service.find_issues(
            session_state.task_description,
            result["content"],
        )
        if not issues:
            return result

        revised_result = await self.agent_runner.run(
            agent_type=session_state.agent_type,
            task_description=session_state.task_description,
            answers=session_state.answers,
            model=model,
            max_output_tokens=max_output_tokens,
            qc_issues=issues,
        )
        revised_result["warnings"] = (revised_result.get("warnings") or []) + issues
        return revised_result

    async def _finalize_session(
        self,
        db_session: AsyncSession,
        session_state: TaskSessionState,
        result: Dict[str, Any],
        usage: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._log_task_completed(session_state, usage)

        image_payload = await self.task_image_service.generate_for_task_session(session_state)

        await TaskSessionService.delete(db_session, session_state.session_id)
        await db_session.commit()

        return {
            "status": "done",
            "session_id": session_state.session_id,
            "result": result,
            "image": image_payload,
        }

    @staticmethod
    def _log_task_completed(
        session_state: TaskSessionState,
        usage: Dict[str, Any],
    ) -> None:
        logger.info(
            "task_completed",
            extra={
                "request_id": session_state.request_id,
                "user_id": session_state.user_id,
                "agent_type": session_state.agent_type,
                "tokens": usage.get("total_tokens", "-") if usage else "-",
            },
        )
