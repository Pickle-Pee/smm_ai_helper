from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.agents import (
    AnalyticsAgent,
    ContentAgent,
    PromoAgent,
    StrategyAgent,
    TrendsAgent,
)
from app.agents.utils import safe_json_parse
from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.services.image_orchestrator import ImageOrchestrator


logger = logging.getLogger(__name__)


AGENT_MAP = {
    "strategy": StrategyAgent(),
    "content": ContentAgent(),
    "analytics": AnalyticsAgent(),
    "promo": PromoAgent(),
    "trends": TrendsAgent(),
}


@dataclass
class TaskSession:
    session_id: str
    agent_type: str
    task_description: str
    mode: str
    answers: Dict[str, Any] = field(default_factory=dict)
    questions_asked: int = 0
    request_id: str = "-"
    user_id: str = "anonymous"


class OrchestratorService:
    def __init__(self) -> None:
        self.sessions: Dict[str, TaskSession] = {}
        self.image_orchestrator = ImageOrchestrator()

    def _fallback_decision(self, agent_type: str) -> Dict[str, Any]:
        complexity = "hard" if agent_type in {"strategy", "analytics"} else "light"
        model = (
            settings.DEFAULT_TEXT_MODEL_HARD
            if complexity == "hard"
            else settings.DEFAULT_TEXT_MODEL_LIGHT
        )
        return {
            "complexity": complexity,
            "model": model,
            "max_output_tokens": 1200,
            "needs_clarification": False,
            "next_questions": [],
            "needs_qc": complexity == "hard",
        }

    async def _route_task(
        self, agent_type: str, task_description: str, answers: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        prompt = f"""
Ты — маршрутизатор задач SMM. Верни строго JSON:
{{
  "complexity": "light|hard",
  "model": "gpt-4o-mini|gpt-5-mini",
  "max_output_tokens": number,
  "needs_clarification": boolean,
  "next_questions": [{{"key":"...", "question":"..."}}],
  "needs_qc": boolean
}}

Правила:
- light → посты, идеи, простые тексты
- hard → стратегии, анализ, воронки

Agent type: {agent_type}
Описание: {task_description}
Ответы: {answers}
"""
        messages = [
            {"role": "system", "content": "Ты — строгий JSON-роутер."},
            {"role": "user", "content": prompt},
        ]
        try:
            content, usage = await openai_chat(
                messages=messages,
                model=settings.DEFAULT_TEXT_MODEL_LIGHT,
                temperature=0.2,
                max_output_tokens=400,
            )
            decision = safe_json_parse(content)
            complexity = decision.get("complexity")
            if complexity not in {"light", "hard"}:
                complexity = "light"
            model = decision.get("model")
            if model not in {"gpt-4o-mini", "gpt-5-mini"}:
                model = (
                    settings.DEFAULT_TEXT_MODEL_HARD
                    if complexity == "hard"
                    else settings.DEFAULT_TEXT_MODEL_LIGHT
                )
            decision["complexity"] = complexity
            decision["model"] = model
            decision.setdefault("max_output_tokens", 1200)
            decision.setdefault("needs_clarification", False)
            decision.setdefault("next_questions", [])
            decision.setdefault("needs_qc", complexity == "hard")
            return decision, usage
        except Exception:
            return self._fallback_decision(agent_type), {}

    async def _clarify(
        self,
        task_description: str,
        answers: Dict[str, Any],
        remaining: int,
    ) -> List[Dict[str, str]]:
        prompt = f"""
Нужно уточнить задачу. Верни от 1 до {min(3, remaining)} вопросов JSON:
[
  {{"key": "...", "question": "..."}}
]

Описание: {task_description}
Ответы: {answers}
"""
        messages = [
            {"role": "system", "content": "Ты — уточняющий агент. Отвечай JSON."},
            {"role": "user", "content": prompt},
        ]
        content, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=0.3,
            max_output_tokens=300,
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return [{"key": "details", "question": "Расскажи чуть подробнее про задачу."}]

    def _format_result(self, agent_type: str, result: Dict[str, Any]) -> str:
        if agent_type == "strategy":
            summary_text = result.get("summary_text") or ""
            structured = result.get("structured") or {}
            positioning = structured.get("positioning") or {}
            core_msg = positioning.get("core_message") or ""
            utp_list = positioning.get("utp") or []
            lines = []
            if summary_text:
                lines.extend(["### Кратко по стратегии", summary_text, ""])
            if core_msg:
                lines.extend(["### Позиционирование", core_msg, ""])
            if utp_list:
                lines.append("### Ключевые УТП")
                lines.extend([f"- {u}" for u in utp_list[:5]])
            return "\n".join(lines).strip()

        if agent_type == "content":
            plan_md = result.get("raw_plan_markdown") or ""
            posts = result.get("posts") or []
            lines = []
            if plan_md:
                lines.append("### Контент-план")
                lines.append(plan_md)
            if posts:
                post_text = posts[0].get("post", {}).get("full_text") or ""
                if post_text:
                    lines.extend(["", "### Пример поста", post_text])
            return "\n".join(lines).strip()

        if agent_type == "analytics":
            next_steps = result.get("next_steps") or []
            if not next_steps:
                return "Пока нет явных рекомендаций — попробуйте уточнить задачу."
            lines = ["### Что делать дальше"]
            lines.extend([f"- {step}" for step in next_steps[:10]])
            return "\n".join(lines)

        if agent_type == "promo":
            overall = result.get("overall_approach") or []
            hypotheses = result.get("hypotheses") or []
            lines = []
            if overall:
                lines.append("### Подход к рекламе")
                lines.extend([f"- {line}" for line in overall[:5]])
            if hypotheses:
                lines.append("\n### Стартовые гипотезы")
                for h in hypotheses[:3]:
                    name = h.get("name") or "Гипотеза"
                    segment = h.get("segment")
                    offer = h.get("offer")
                    angle = h.get("angle")
                    lines.append(f"- **{name}**")
                    if segment:
                        lines.append(f"  - ЦА: {segment}")
                    if offer:
                        lines.append(f"  - Оффер: {offer}")
                    if angle:
                        lines.append(f"  - Идея: {angle}")
            return "\n".join(lines).strip()

        if agent_type == "trends":
            exp = result.get("experiment_roadmap") or []
            if not exp:
                return "Пока нет явных идей — попробуйте уточнить нишу или формат."
            lines = ["### Эксперименты, которые можно запустить"]
            for e in exp[:5]:
                name = e.get("experiment_name") or "Эксперимент"
                hyp = e.get("hypothesis")
                fmt = e.get("format")
                lines.append(f"- **{name}**")
                if fmt:
                    lines.append(f"  - Формат: {fmt}")
                if hyp:
                    lines.append(f"  - Гипотеза: {hyp}")
            return "\n".join(lines)

        return json.dumps(result, ensure_ascii=False, indent=2)

    async def _run_worker(
        self,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any],
        model: str,
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        agent = AGENT_MAP.get(agent_type)
        if not agent:
            raise ValueError("Unknown agent type")

        brief = {"task_description": task_description, **answers}
        kwargs: Dict[str, Any] = {}
        if agent_type == "content":
            period = answers.get("period") or answers.get("days")
            if period:
                kwargs["days"] = int(period)

        agent.model_override = model
        agent.max_output_tokens_override = max_output_tokens
        result = await agent.run(brief, **kwargs)
        agent.model_override = None
        agent.max_output_tokens_override = None
        content = self._format_result(agent_type, result)
        return {
            "content": content,
            "format": "markdown",
            "assumptions": [],
            "confidence": "medium",
            "warnings": [],
        }

    async def _run_qc(self, task_description: str, content: str) -> List[str]:
        prompt = f"""
Ты — QC редактор. Проверь ответ и верни JSON:
{{"status": "ok|revise", "issues": ["..."]}}

Задача: {task_description}
Ответ: {content}
"""
        messages = [
            {"role": "system", "content": "Ты — строгий QC. Отвечай JSON."},
            {"role": "user", "content": prompt},
        ]
        content_resp, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=0.2,
            max_output_tokens=300,
        )
        data = safe_json_parse(content_resp)
        if data.get("status") == "revise":
            return data.get("issues") or []
        return []

    async def start_task(
        self,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any],
        mode: str,
        request_id: str = "-",
        user_id: str = "anonymous",
    ) -> Dict[str, Any]:
        session_id = uuid.uuid4().hex
        session = TaskSession(
            session_id=session_id,
            agent_type=agent_type,
            task_description=task_description,
            mode=mode,
            answers=answers or {},
            request_id=request_id,
            user_id=user_id,
        )
        self.sessions[session_id] = session
        return await self._continue_session(session)

    async def answer(
        self,
        session_id: str,
        key: str,
        value: str,
    ) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError("Unknown session")
        session.answers[key] = value
        return await self._continue_session(session)

    def get_session(self, session_id: str) -> TaskSession | None:
        return self.sessions.get(session_id)

    async def _continue_session(self, session: TaskSession) -> Dict[str, Any]:
        decision, usage = await self._route_task(
            session.agent_type, session.task_description, session.answers
        )
        needs_clarification = decision.get("needs_clarification", False)
        max_questions = 6

        if needs_clarification and session.questions_asked < max_questions:
            remaining = max_questions - session.questions_asked
            questions = decision.get("next_questions") or await self._clarify(
                session.task_description, session.answers, remaining
            )
            session.questions_asked += len(questions)
            return {
                "status": "need_info",
                "session_id": session.session_id,
                "questions": questions[:3],
            }

        result = await self._run_worker(
            agent_type=session.agent_type,
            task_description=session.task_description,
            answers=session.answers,
            model=decision.get("model") or settings.DEFAULT_TEXT_MODEL_LIGHT,
            max_output_tokens=int(decision.get("max_output_tokens") or 1200),
        )
        needs_qc = decision.get("needs_qc", False) or result.get("confidence") == "low"
        if needs_qc:
            issues = await self._run_qc(session.task_description, result["content"])
            if issues:
                session.answers["qc_issues"] = issues
                result = await self._run_worker(
                    agent_type=session.agent_type,
                    task_description=session.task_description,
                    answers=session.answers,
                    model=decision.get("model") or settings.DEFAULT_TEXT_MODEL_LIGHT,
                    max_output_tokens=int(decision.get("max_output_tokens") or 1200),
                )
                result["warnings"] = issues

        logger.info(
            "task_completed",
            extra={
                "request_id": session.request_id,
                "user_id": session.user_id,
                "agent_type": session.agent_type,
                "tokens": usage.get("total_tokens", "-") if usage else "-",
            },
        )

        image_payload = None
        if session.mode in {"image", "text+image"}:
            image_payload = await self.image_orchestrator.generate(
                platform=session.answers.get("platform", "auto"),
                use_case=session.answers.get("use_case", "auto"),
                message=session.task_description,
                brand=session.answers.get("brand"),
                overlay=session.answers.get("overlay"),
                variants=int(session.answers.get("variants", 1) or 1),
                user_id=session.user_id,
                request_id=session.request_id,
            )

        self.sessions.pop(session.session_id, None)
        return {
            "status": "done",
            "session_id": session.session_id,
            "result": result,
            "image": image_payload,
        }
