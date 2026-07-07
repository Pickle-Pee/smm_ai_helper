from __future__ import annotations

import json
from typing import Any, Dict, List, Union

from app.agents.utils import safe_json_parse
from app.config import settings
from app.llm.openai_text import chat as openai_chat


def safe_json_parse_any(raw: str) -> Union[Dict[str, Any], List[Any]]:
    """
    Parse either a JSON object or a JSON array from an LLM response.
    """
    value = raw.strip()
    if value.startswith("["):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

        first = value.find("[")
        last = value.rfind("]")
        if first != -1 and last != -1 and last > first:
            return json.loads(value[first : last + 1])

    return safe_json_parse(raw)


class ClarificationService:
    """Generates short clarification questions for incomplete task briefs."""

    async def generate_questions(
        self,
        task_description: str,
        answers: Dict[str, Any],
        remaining: int,
    ) -> List[Dict[str, str]]:
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
                questions: List[Dict[str, str]] = []
                for item in data:
                    if isinstance(item, dict) and "question" in item:
                        questions.append(
                            {
                                "key": str(item.get("key", "details")),
                                "question": str(item.get("question")),
                            }
                        )
                return questions[:3]
        except Exception:
            pass

        return [
            {
                "key": "details",
                "question": "Расскажи чуть подробнее про задачу (цель + аудитория + площадка).",
            }
        ]
