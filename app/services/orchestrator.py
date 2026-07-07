from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.utils import safe_json_parse
from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.services.agent_runner import AgentRunner
from app.services.image_orchestrator import ImageOrchestrator
from app.services.task_router import TaskRouter
from app.services.task_session_service import TaskSessionService, TaskSessionState

logger = logging.getLogger(__name__)


def safe_json_parse_any(raw: str) -> Union[Dict[str, Any], List[Any]]:
    """
    Более универсальный парсер:
    - если ответ — JSON-объект, вернёт dict через safe_json_parse
    - если ответ — JSON-массив, распарсит как list
    """
    s = raw.strip()
    if s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

        first = s.find("[")
        last = s.rfind("]")
        if first != -1 and last != -1 and last > first:
            return json.loads(s[first : last + 1])

    return safe_json_parse(raw)


class OrchestratorService:
    def __init__(self) -> None:
        self.task_router = TaskRouter()
        self.agent_runner = AgentRunner()
        self.image_orchestrator = ImageOrchestrator()

    # -------------------------
    # Clarification
    # -------------------------

    async def _clarify(
        self,
        task_description: str,
        answers: Dict[str, Any],
        remaining: int,
    ) -> List[Dict[str, str]]:
        """
        Уточнение тоже всегда на LIGHT. Возвращаем до 1–3 вопросов.
        """
        prompt = f"""
Нужно уточнить задачу. Верни от 1 до {min(3, remaining)} вопросов строго JSON-массивом:
[
  {{"key": "...", "question": "..."}}
]

Правила:
- максимум 3 вопроса
- вопросы должны быть короткими и реально нужными
- если можно продолжать без вопросов — верни пустой массив []

Описание: {task_description}
Ответы: {answers}
""".strip()

        messages = [
            {"role": "system", "content": "Ты — уточняющий агент. Только JSON (массив)."},
            {"role": "user", "content": prompt},
        ]

        content, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=None,
            max_output_tokens=1500,
        )

        try:
            data = safe_json_parse_any(content)
            if isinstance(data, list):
                out: List[Dict[str, str]] = []
                for item in data:
                    if isinstance(item, dict) and "question" in item:
                        out.append({"key": str(item.get("key", "details")), "question": str(item.get("question"))})
                return out[:3]
        except Exception:
            pass

        return [{"key": "details", "question": "Расскажи чуть подробнее про задачу (цель + аудитория + площадка)."}]

    # -------------------------
    # QC
    # -------------------------

    async def _run_qc(self, task_description: str, content: str) -> List[str]:
        """
        QC всегда на LIGHT модели.
        """
        prompt = f"""
Ты — QC редактор. Проверь ответ и верни строго JSON:
{{"status": "ok|revise", "issues": ["..."]}}

Правила:
- issues: только конкретные замечания (что исправить), максимум 6
- если всё ок — status="ok" и issues=[]
- обращай внимание на: абстрактные формулировки, отсутствие конкретных шагов/примеров, лишняя вода

Задача: {task_description}
Ответ: {content}
""".strip()

        messages = [
            {"role": "system", "content": "Ты — строгий QC. Только JSON."},
            {"role": "user", "content": prompt},
        ]

        content_resp, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=None,
            max_output_tokens=1500,
            response_format={"type": "json_object"},
        )

        data = safe_json_parse(content_resp)
        if data.get("status") == "revise":
            issues = data.get("issues") or []
            if isinstance(issues, list):
                return [str(x) for x in issues[:6]]
        return []

    # -------------------------
    # Public API
    # -------------------------

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
            session_state.agent_type, session_state.task_description, session_state.answers
        )

        needs_clarification = decision.get("needs_clarification", False)
        max_questions = 6

        if needs_clarification and session_state.questions_asked < max_questions:
            remaining = max_questions - session_state.questions_asked
            next_questions = decision.get("next_questions") or []
            questions = next_questions if next_questions else await self._clarify(
                session_state.task_description, session_state.answers, remaining
            )

            session_state.questions_asked += len(questions)
            await TaskSessionService.save(db_session, session_state)
            await db_session.commit()
            return {
                "status": "need_info",
                "session_id": session_state.session_id,
                "questions": questions[:3],
            }

        model = decision.get("model") or settings.DEFAULT_TEXT_MODEL_LIGHT
        max_output_tokens = int(decision.get("max_output_tokens") or (1600 if decision.get("complexity") == "hard" else 900))

        result = await self.agent_runner.run(
            agent_type=session_state.agent_type,
            task_description=session_state.task_description,
            answers=session_state.answers,
            model=model,
            max_output_tokens=max_output_tokens,
        )

        needs_qc = bool(decision.get("needs_qc", False)) or result.get("confidence") == "low"
        if needs_qc:
            issues = await self._run_qc(session_state.task_description, result["content"])
            if issues:
                result = await self.agent_runner.run(
                    agent_type=session_state.agent_type,
                    task_description=session_state.task_description,
                    answers=session_state.answers,
                    model=model,
                    max_output_tokens=max_output_tokens,
                    qc_issues=issues,
                )
                result["warnings"] = (result.get("warnings") or []) + issues

        logger.info(
            "task_completed",
            extra={
                "request_id": session_state.request_id,
                "user_id": session_state.user_id,
                "agent_type": session_state.agent_type,
                "tokens": usage.get("total_tokens", "-") if usage else "-",
            },
        )

        image_payload = None
        if session_state.mode in {"image", "text+image"}:
            image_payload = await self.image_orchestrator.generate(
                platform=session_state.answers.get("platform", "auto"),
                use_case=session_state.answers.get("use_case", "auto"),
                message=session_state.task_description,
                brand=session_state.answers.get("brand"),
                overlay=session_state.answers.get("overlay"),
                variants=int(session_state.answers.get("variants", 1) or 1),
                user_id=session_state.user_id,
                request_id=session_state.request_id,
            )

        await TaskSessionService.delete(db_session, session_state.session_id)
        await db_session.commit()

        return {
            "status": "done",
            "session_id": session_state.session_id,
            "result": result,
            "image": image_payload,
        }
