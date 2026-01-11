# app/agents/orchestrator_agent.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.agents.utils import safe_json_parse

from .strategy_agent import StrategyAgent
from .trends_agent import TrendsAgent
from .content_agent import ContentAgent
from .promo_agent import PromoAgent
from .analytics_agent import AnalyticsAgent


AGENT_REGISTRY: Dict[str, Type] = {
    "strategy": StrategyAgent,
    "trends": TrendsAgent,
    "content": ContentAgent,
    "promo": PromoAgent,
    "analytics": AnalyticsAgent,
}


def _normalize_tasks(brief: Dict[str, Any]) -> List[str]:
    """
    Определяем, какие агенты запускать.
    Поддержка:
    - brief["agent_type"] = "content"
    - brief["tasks"] = ["content", "strategy"]
    - brief["full_pipeline"] = True
    """
    if brief.get("full_pipeline") is True:
        return ["strategy", "trends", "content", "promo", "analytics"]

    tasks = brief.get("tasks")
    if isinstance(tasks, list) and tasks:
        out = []
        for t in tasks:
            t = str(t).strip().lower()
            if t in AGENT_REGISTRY:
                out.append(t)
        return out or ["content"]

    agent_type = (brief.get("agent_type") or "").strip().lower()
    if agent_type in AGENT_REGISTRY:
        return [agent_type]

    # fallback
    return ["content"]


class OrchestratorAgent:
    """
    Оркестратор уровня "агентов" (не путать с сервисным orchestrator.py).
    Запускает нужные агенты по brief, делает QC и возвращает сводку.
    """

    def __init__(self) -> None:
        pass

    async def _qc_check(self, user_task: str, text: str) -> List[str]:
        """
        QC: быстрый и дешёвый. Возвращает список issues.
        """
        prompt = f"""
Ты — редактор качества. Верни строго JSON:
{{"status":"ok|revise", "issues":["..."]}}

Проверь:
- есть ли конкретика/примеры
- нет ли воды/общих слов
- есть ли понятные следующие шаги
- ответ соответствует задаче

Задача пользователя: {user_task}
Ответ: {text}
""".strip()

        messages = [
            {"role": "system", "content": "Ты — строгий QC. Только JSON."},
            {"role": "user", "content": prompt},
        ]

        content, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=0.2,
            max_output_tokens=320,
            response_format={"type": "json_object"},
        )
        data = safe_json_parse(content)
        if data.get("status") == "revise":
            issues = data.get("issues") or []
            if isinstance(issues, list):
                return [str(x) for x in issues[:8]]
        return []

    def _extract_user_facing_text(self, agent_name: str, result: Dict[str, Any]) -> str:
        """
        Достаём “текст для пользователя” из структур, чтобы QC мог проверить.
        """
        if agent_name == "strategy":
            return (result.get("full_strategy") or result.get("summary_text") or "").strip()
        if agent_name == "content":
            # берем первый пример поста, если есть
            posts = result.get("posts") or []
            if posts and isinstance(posts, list):
                post0 = posts[0].get("post") if isinstance(posts[0], dict) else None
                if isinstance(post0, dict):
                    return (post0.get("full_text") or "").strip()
            return (result.get("raw_plan_markdown") or "").strip()
        if agent_name == "analytics":
            # если next_steps объекты — собираем
            ns = result.get("next_steps") or []
            if isinstance(ns, list) and ns:
                if isinstance(ns[0], dict):
                    lines = []
                    for s in ns[:6]:
                        step = s.get("step") or ""
                        impact = s.get("impact") or ""
                        effort = s.get("effort") or ""
                        how = s.get("how_to_do") or ""
                        lines.append(f"- {step} ({impact}, {effort}) {how}".strip())
                    return "\n".join(lines).strip()
                return "\n".join([str(x) for x in ns[:8]]).strip()
            return ""
        if agent_name == "promo":
            hyps = result.get("hypotheses") or []
            if isinstance(hyps, list) and hyps:
                h0 = hyps[0] if isinstance(hyps[0], dict) else {}
                return f"{h0.get('name','Гипотеза')}: {h0.get('angle','')}".strip()
            return ""
        if agent_name == "trends":
            exp = result.get("experiment_roadmap") or []
            if isinstance(exp, list) and exp:
                e0 = exp[0] if isinstance(exp[0], dict) else {}
                return f"{e0.get('experiment_name','Эксперимент')}: {e0.get('hypothesis','')}".strip()
            return ""
        return ""

    async def _run_agent_once(
        self,
        agent_name: str,
        brief: Dict[str, Any],
        model: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        qc_issues: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        agent_cls = AGENT_REGISTRY[agent_name]
        agent = agent_cls()

        # overrides на локальном инстансе безопасны
        if model:
            agent.model_override = model
        if max_output_tokens is not None:
            agent.max_output_tokens_override = max_output_tokens

        # пробрасываем qc_issues в brief, чтобы qc_block сработал
        if qc_issues:
            brief = dict(brief)
            brief["qc_issues"] = qc_issues

        return await agent.run(brief)

    async def run(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        tasks = _normalize_tasks(brief)

        # лёгкая политика моделей: hard только для strategy/analytics
        def pick_model(task: str) -> str:
            if task in {"strategy", "analytics"}:
                return settings.DEFAULT_TEXT_MODEL_HARD
            return settings.DEFAULT_TEXT_MODEL_LIGHT

        results: Dict[str, Any] = {}
        warnings: List[str] = []

        # user_task для QC
        user_task = str(brief.get("task_description") or brief.get("message") or "SMM задача")

        for t in tasks:
            model = pick_model(t)

            # первый прогон
            out = await self._run_agent_once(t, brief, model=model, max_output_tokens=1600)

            # QC только для "тяжелых" или если явно requested
            qc_needed = t in {"strategy", "analytics"} or brief.get("qc") is True
            if qc_needed:
                text = self._extract_user_facing_text(t, out)
                if text:
                    issues = await self._qc_check(user_task, text)
                    if issues:
                        # повторный прогон с учетом QC замечаний
                        out = await self._run_agent_once(
                            t, brief, model=model, max_output_tokens=1800, qc_issues=issues
                        )
                        warnings.extend([f"{t}: {x}" for x in issues])

            results[t] = out

        # итоговая короткая сводка (для UI/бота)
        summary_parts: List[str] = []
        if "strategy" in results:
            summary_parts.append(results["strategy"].get("summary_text", "").strip())
        if "content" in results:
            # покажем 1 пост
            posts = results["content"].get("posts") or []
            if posts:
                p0 = posts[0].get("post", {})
                if isinstance(p0, dict) and p0.get("full_text"):
                    summary_parts.append("Пример поста:\n" + p0["full_text"].strip())

        summary = "\n\n".join([s for s in summary_parts if s])

        return {
            "tasks": tasks,
            "results": results,
            "summary": summary,
            "warnings": warnings,
        }
