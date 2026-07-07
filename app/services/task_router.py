from __future__ import annotations

from typing import Any, Dict, Tuple

from app.agents.utils import safe_json_parse
from app.config import settings
from app.llm.openai_text import chat as openai_chat


class TaskRouter:
    """Routes task requests to model/clarification/QC decisions."""

    def fallback_decision(self, agent_type: str) -> Dict[str, Any]:
        complexity = "hard" if agent_type in {"strategy", "analytics"} else "light"
        model = (
            settings.DEFAULT_TEXT_MODEL_HARD
            if complexity == "hard"
            else settings.DEFAULT_TEXT_MODEL_LIGHT
        )
        return {
            "complexity": complexity,
            "model": model,
            "max_output_tokens": 1200 if complexity == "hard" else 900,
            "needs_clarification": False,
            "next_questions": [],
            "needs_qc": complexity == "hard",
        }

    async def route(
        self,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Route on the light model only.

        The router is not allowed to pick arbitrary models; it only decides
        light/hard complexity and normalized runtime limits.
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
- по возможности НЕ спрашивай вопросы: если можно продолжить с допущениями — needs_clarification=false

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
                temperature=None,
                max_output_tokens=1500,
                response_format={"type": "json_object"},
            )
            decision = safe_json_parse(content)
            return self._normalize_decision(agent_type, decision), usage
        except Exception:
            return self.fallback_decision(agent_type), {}

    def _normalize_decision(
        self,
        agent_type: str,
        decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        complexity = decision.get("complexity")
        if complexity not in {"light", "hard"}:
            complexity = "hard" if agent_type in {"strategy", "analytics"} else "light"

        model = (
            settings.DEFAULT_TEXT_MODEL_HARD
            if complexity == "hard"
            else settings.DEFAULT_TEXT_MODEL_LIGHT
        )

        max_output_tokens = decision.get("max_output_tokens")
        if not isinstance(max_output_tokens, int):
            max_output_tokens = 1600 if complexity == "hard" else 900
        else:
            max_output_tokens = max(600, min(int(max_output_tokens), 2400))

        return {
            **decision,
            "complexity": complexity,
            "model": model,
            "max_output_tokens": max_output_tokens,
            "needs_clarification": bool(decision.get("needs_clarification", False)),
            "next_questions": decision.get("next_questions") or [],
            "needs_qc": bool(decision.get("needs_qc", complexity == "hard")),
        }
