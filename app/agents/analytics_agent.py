# app/agents/analytics_agent.py
from typing import Any, Dict

from .base import BaseAgent
from .utils import normalize_brief


class AnalyticsAgent(BaseAgent):
    system_prompt = (
        "Ты — маркетинговый аналитик. "
        "Тебе важны не красивые дашборды, а простые ответы: что работает, что нет и что делать дальше."
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        # Если пользователь прислал какие-то метрики — пробрасываем как есть
        raw_metrics = brief.get("metrics")

        instruction = f"""
Нужно помочь с аналитикой SMM-активностей.

Контекст брифа:
{c}

(A) Если есть сырые метрики/описание ситуации, используй их:
{raw_metrics}

(B) Если метрик нет — помоги сделать план аналитики и минимальный набор измерений.
"""

        schema_hint = """
{
  "metrics_plan": [
    {
      "channel": "Telegram",
      "metrics": [
        {
          "name": "ER",
          "how_to_calc": "как считать простым языком",
          "why_important": "зачем смотреть"
        }
      ]
    }
  ],
  "benchmarks": [
    {
      "metric": "ER",
      "good": "примерное значение 'хорошо'",
      "bad": "примерное значение 'плохо'",
      "comment": "важные оговорки"
    }
  ],
  "diagnosis": [
    "если из контекста видно какие-то проблемы, опиши их списком"
  ],
  "next_steps": [
    "конкретное действие 1",
    "конкретное действие 2"
  ]
}
"""

        data = await self.llm_json(instruction, schema_hint)
        return data
