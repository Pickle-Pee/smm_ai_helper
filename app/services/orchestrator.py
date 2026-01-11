from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type, Union

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

# ВАЖНО: храним классы, а не синглтоны (иначе гонки при параллельных запросах)
AGENT_MAP: Dict[str, Type] = {
    "strategy": StrategyAgent,
    "content": ContentAgent,
    "analytics": AnalyticsAgent,
    "promo": PromoAgent,
    "trends": TrendsAgent,
}


def safe_json_parse_any(raw: str) -> Union[Dict[str, Any], List[Any]]:
    """
    Более универсальный парсер:
    - если ответ — JSON-объект, вернёт dict через safe_json_parse
    - если ответ — JSON-массив, распарсит как list
    """
    s = raw.strip()
    # быстрый путь: если явно массив
    if s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

        # попробуем вырезать от первого [ до последнего ]
        first = s.find("[")
        last = s.rfind("]")
        if first != -1 and last != -1 and last > first:
            return json.loads(s[first : last + 1])

    # иначе — обычный safe_json_parse (объект)
    return safe_json_parse(raw)


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

    # -------------------------
    # Routing / clarification
    # -------------------------

    def _fallback_decision(self, agent_type: str) -> Dict[str, Any]:
        complexity = "hard" if agent_type in {"strategy", "analytics"} else "light"
        model = settings.DEFAULT_TEXT_MODEL_HARD if complexity == "hard" else settings.DEFAULT_TEXT_MODEL_LIGHT
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
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Роутер всегда работает на LIGHT модели (стабильно/дёшево).
        Не даём роутеру выбирать произвольные модели — только light/hard через decision.
        """
        prompt = f"""
Ты — маршрутизатор задач SMM. Верни строго JSON:
{{
  "complexity": "light|hard",
  "max_output_tokens": number,
  "needs_clarification": boolean,
  "next_questions": [{{"key":"...", "question":"..."}}],
  "needs_qc": boolean
}}

Правила:
- light → посты, идеи, простые тексты
- hard → стратегии, анализ, воронки
- max_output_tokens: light 700–1200, hard 1200–2200

Agent type: {agent_type}
Описание: {task_description}
Ответы: {answers}
""".strip()

        messages = [
            {"role": "system", "content": "Ты — строгий JSON-роутер. Только JSON."},
            {"role": "user", "content": prompt},
        ]

        try:
            content, usage = await openai_chat(
                messages=messages,
                model=settings.DEFAULT_TEXT_MODEL_LIGHT,
                temperature=0.2,  # ok для gpt-4o-mini
                max_output_tokens=450,
                response_format={"type": "json_object"},
            )
            decision = safe_json_parse(content)

            complexity = decision.get("complexity")
            if complexity not in {"light", "hard"}:
                complexity = "light"

            # модель выбираем сами по complexity
            model = settings.DEFAULT_TEXT_MODEL_HARD if complexity == "hard" else settings.DEFAULT_TEXT_MODEL_LIGHT

            decision["complexity"] = complexity
            decision["model"] = model

            mot = decision.get("max_output_tokens")
            if not isinstance(mot, int):
                decision["max_output_tokens"] = 1200 if complexity == "hard" else 900

            decision["needs_clarification"] = bool(decision.get("needs_clarification", False))
            decision["next_questions"] = decision.get("next_questions") or []
            decision["needs_qc"] = bool(decision.get("needs_qc", complexity == "hard"))

            return decision, usage
        except Exception:
            return self._fallback_decision(agent_type), {}

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
            temperature=0.3,
            max_output_tokens=350,
        )

        try:
            data = safe_json_parse_any(content)
            if isinstance(data, list):
                # нормализуем структуру
                out: List[Dict[str, str]] = []
                for item in data:
                    if isinstance(item, dict) and "question" in item:
                        out.append({"key": str(item.get("key", "details")), "question": str(item.get("question"))})
                return out[:3]
        except Exception:
            pass

        return [{"key": "details", "question": "Расскажи чуть подробнее про задачу (цель + аудитория + площадка)."}]

    # -------------------------
    # Formatting
    # -------------------------

    def _format_result(self, agent_type: str, result: Dict[str, Any]) -> str:
        """
        ВАЖНО: не “скомкивать” ответы.
        Возвращаем более полный текст. Если есть готовый user_answer/full_* — используем.
        """

        # Новый стандарт (если начнёшь внедрять): агенты могут отдавать user_answer
        if isinstance(result.get("user_answer"), str) and result["user_answer"].strip():
            return result["user_answer"].strip()

        if agent_type == "strategy":
            # предпочитаем полный текст стратегии, если он есть
            full = result.get("full_strategy")
            if isinstance(full, str) and full.strip():
                return full.strip()

            summary_text = (result.get("summary_text") or "").strip()
            structured = result.get("structured") or {}

            # если только structured — соберём читабельно, но не 3 строки
            parts: List[str] = []
            if summary_text:
                parts += ["### Кратко", summary_text, ""]

            positioning = structured.get("positioning") or {}
            if positioning:
                core = positioning.get("core_message")
                utp = positioning.get("utp") or []
                rtb = positioning.get("reasons_to_believe") or []
                if core:
                    parts += ["### Позиционирование", f"**Сообщение:** {core}", ""]
                if utp:
                    parts.append("### УТП")
                    parts += [f"- {x}" for x in utp[:8]]
                    parts.append("")
                if rtb:
                    parts.append("### Почему верить")
                    parts += [f"- {x}" for x in rtb[:6]]
                    parts.append("")

            rubrics = structured.get("content_rubrics") or []
            if rubrics:
                parts.append("### Рубрики контента")
                for r in rubrics[:7]:
                    name = r.get("name")
                    goal = r.get("goal")
                    ex = r.get("examples") or []
                    if name:
                        parts.append(f"- **{name}**" + (f" — {goal}" if goal else ""))
                        for e in ex[:3]:
                            parts.append(f"  - {e}")
                parts.append("")

            funnel = structured.get("funnel") or {}
            if funnel:
                parts.append("### Воронка (что делаем)")
                for stage in ["awareness", "consideration", "conversion", "retention"]:
                    items = funnel.get(stage) or []
                    if items:
                        parts.append(f"- **{stage.capitalize()}**:")
                        parts += [f"  - {x}" for x in items[:5]]
                parts.append("")

            text = "\n".join([p for p in parts if p is not None]).strip()
            return text or json.dumps(result, ensure_ascii=False, indent=2)

        if agent_type == "content":
            plan_md = (result.get("raw_plan_markdown") or "").strip()
            posts = result.get("posts") or []

            parts: List[str] = []
            if plan_md:
                parts += ["### Контент-план", plan_md, ""]

            # показываем несколько постов (не 1)
            if posts:
                parts.append("### Примеры постов")
                for i, p in enumerate(posts[:3], start=1):
                    post_obj = p.get("post") or {}
                    title = post_obj.get("title") or f"Пост #{i}"
                    full_text = (post_obj.get("full_text") or "").strip()
                    parts.append(f"**{title}**")
                    if full_text:
                        parts.append(full_text)
                    parts.append("")

            text = "\n".join(parts).strip()
            return text or json.dumps(result, ensure_ascii=False, indent=2)

        if agent_type == "analytics":
            # если агент отдаёт next_steps — ок, но попробуем ещё вытянуть summary/plan если есть
            next_steps = result.get("next_steps") or []
            if isinstance(next_steps, list) and next_steps:
                lines = ["### План действий (следующие шаги)"]
                lines += [f"- {step}" for step in next_steps[:12]]
                return "\n".join(lines).strip()

            if isinstance(result.get("user_answer"), str):
                return result["user_answer"].strip()

            return json.dumps(result, ensure_ascii=False, indent=2)

        if agent_type == "promo":
            if isinstance(result.get("user_answer"), str) and result["user_answer"].strip():
                return result["user_answer"].strip()

            overall = result.get("overall_approach") or []
            hypotheses = result.get("hypotheses") or []
            lines: List[str] = []
            if overall:
                lines.append("### Подход к рекламе")
                lines.extend([f"- {line}" for line in overall[:8]])
                lines.append("")
            if hypotheses:
                lines.append("### Гипотезы")
                for h in hypotheses[:5]:
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
                        lines.append(f"  - Креативный угол: {angle}")
            return "\n".join(lines).strip() or json.dumps(result, ensure_ascii=False, indent=2)

        if agent_type == "trends":
            if isinstance(result.get("user_answer"), str) and result["user_answer"].strip():
                return result["user_answer"].strip()

            exp = result.get("experiment_roadmap") or []
            if exp:
                lines = ["### Эксперименты, которые можно запустить"]
                for e in exp[:7]:
                    name = e.get("experiment_name") or "Эксперимент"
                    hyp = e.get("hypothesis")
                    fmt = e.get("format")
                    lines.append(f"- **{name}**")
                    if fmt:
                        lines.append(f"  - Формат: {fmt}")
                    if hyp:
                        lines.append(f"  - Гипотеза: {hyp}")
                return "\n".join(lines).strip()

            return json.dumps(result, ensure_ascii=False, indent=2)

        return json.dumps(result, ensure_ascii=False, indent=2)

    # -------------------------
    # Worker / QC
    # -------------------------

    async def _run_worker(
        self,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any],
        model: str,
        max_output_tokens: int,
        qc_issues: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        agent_cls = AGENT_MAP.get(agent_type)
        if not agent_cls:
            raise ValueError("Unknown agent type")

        agent = agent_cls()

        # brief — единый словарь
        brief = {"task_description": task_description, **(answers or {})}
        if qc_issues:
            brief["qc_issues"] = qc_issues

        kwargs: Dict[str, Any] = {}
        if agent_type == "content":
            period = answers.get("period") or answers.get("days")
            if period:
                try:
                    kwargs["days"] = int(period)
                except Exception:
                    pass

        # override на локальном инстансе безопасен
        agent.model_override = model
        agent.max_output_tokens_override = max_output_tokens

        result = await agent.run(brief, **kwargs)

        content = self._format_result(agent_type, result)
        return {
            "content": content,
            "format": "markdown",
            "assumptions": result.get("assumptions") or [],
            "confidence": result.get("confidence") or "medium",
            "warnings": result.get("warnings") or [],
        }

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
            temperature=0.2,
            max_output_tokens=350,
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

    async def answer(self, session_id: str, key: str, value: str) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError("Unknown session")
        session.answers[key] = value
        return await self._continue_session(session)

    def get_session(self, session_id: str) -> Optional[TaskSession]:
        return self.sessions.get(session_id)

    async def _continue_session(self, session: TaskSession) -> Dict[str, Any]:
        decision, usage = await self._route_task(
            session.agent_type, session.task_description, session.answers
        )

        needs_clarification = decision.get("needs_clarification", False)
        max_questions = 6

        if needs_clarification and session.questions_asked < max_questions:
            remaining = max_questions - session.questions_asked
            next_questions = decision.get("next_questions") or []
            questions = next_questions if next_questions else await self._clarify(
                session.task_description, session.answers, remaining
            )

            session.questions_asked += len(questions)
            return {
                "status": "need_info",
                "session_id": session.session_id,
                "questions": questions[:3],
            }

        # run worker
        model = decision.get("model") or settings.DEFAULT_TEXT_MODEL_LIGHT
        max_output_tokens = int(decision.get("max_output_tokens") or 1200)

        result = await self._run_worker(
            agent_type=session.agent_type,
            task_description=session.task_description,
            answers=session.answers,
            model=model,
            max_output_tokens=max_output_tokens,
        )

        # QC
        needs_qc = bool(decision.get("needs_qc", False)) or result.get("confidence") == "low"
        if needs_qc:
            issues = await self._run_qc(session.task_description, result["content"])
            if issues:
                # повторный прогон с учетом QC issues
                result = await self._run_worker(
                    agent_type=session.agent_type,
                    task_description=session.task_description,
                    answers=session.answers,
                    model=model,
                    max_output_tokens=max_output_tokens,
                    qc_issues=issues,
                )
                result["warnings"] = (result.get("warnings") or []) + issues

        logger.info(
            "task_completed",
            extra={
                "request_id": session.request_id,
                "user_id": session.user_id,
                "agent_type": session.agent_type,
                "tokens": usage.get("total_tokens", "-") if usage else "-",
            },
        )

        # image mode
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

        # cleanup session
        self.sessions.pop(session.session_id, None)

        return {
            "status": "done",
            "session_id": session.session_id,
            "result": result,
            "image": image_payload,
        }
