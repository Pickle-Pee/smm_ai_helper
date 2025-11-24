# app/agents/strategy_agent.py
from typing import Any, Dict

from .base import BaseAgent
from .utils import normalize_brief


class StrategyAgent(BaseAgent):
    system_prompt = (
        "Ты — старший SMM-стратег, работающий с малым и средним бизнесом. "
        "Думаешь в терминах воронки, юнит-экономики и позиционирования, "
        "но объясняешь простым человеческим языком."
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        instruction = f"""
Нужно разработать SMM-стратегию для проекта.

Данные брифа (используй всё, что полезно):
{c}
"""

        schema_hint = """
{
  "summary": {
    "north_star_metric": "главная метрика успеха SMM",
    "main_bullets": ["краткий тезис 1", "краткий тезис 2"]
  },
  "funnel": {
    "awareness": ["что делаем на верхнем уровне воронки"],
    "consideration": ["что делаем на этапе выбора"],
    "conversion": ["что делаем для заявок/покупок"],
    "retention": ["что делаем для удержания и LTV"]
  },
  "segments": [
    {
      "name": "Название сегмента",
      "short_profile": "кто эти люди",
      "pains": ["боль 1", "боль 2"],
      "triggers": ["триггер 1", "триггер 2"]
    }
  ],
  "positioning": {
    "core_message": "одно главное сообщение бренда",
    "utp": ["УТП 1", "УТП 2", "УТП 3"],
    "reasons_to_believe": ["почему вам верят"]
  },
  "channels": [
    {
      "name": "Telegram",
      "role": "объяснение и прогрев",
      "content_focus": ["какие рубрики в приоритете"],
      "cadence": "какая частота постинга и почему"
    }
  ],
  "content_rubrics": [
    {
      "name": "Рубрика",
      "goal": "какую задачу решает",
      "examples": ["пример темы 1", "пример темы 2"]
    }
  ],
  "risks_and_limits": [
    "потенциальный риск или ограничение"
  ]
}
"""

        data = await self.llm_json(instruction, schema_hint)

        # Краткий текст для быстрого чтения
        bullets = data["summary"]["main_bullets"]
        summary_text = "Кратко:\n" + "\n".join(f"• {b}" for b in bullets)

        # Более развернутая “человеческая” стратегия
        full_lines: list[str] = []
        full_lines.append("NORTH STAR метрика: " + data["summary"]["north_star_metric"])
        full_lines.append("")
        full_lines.append("Ключевые тезисы:")
        full_lines += [f"• {b}" for b in bullets]
        full_lines.append("")
        full_lines.append("Позиционирование:")
        full_lines.append("— " + data["positioning"]["core_message"])
        full_lines.append("УТП:")
        full_lines += [f"• {u}" for u in data["positioning"]["utp"]]
        full_strategy = "\n".join(full_lines)

        return {
            "structured": data,
            "summary_text": summary_text,
            "full_strategy": full_strategy,
        }
