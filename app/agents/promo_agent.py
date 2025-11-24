# app/agents/promo_agent.py
from typing import Any, Dict

from .base import BaseAgent
from .utils import normalize_brief


class PromoAgent(BaseAgent):
    system_prompt = (
        "Ты — медиабаер и перформанс-маркетолог. "
        "Фокус на гипотезах, тестах и понятных правилах, а не на абстракциях."
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        instruction = f"""
Нужно предложить структуру платного продвижения и список рекламных гипотез.

Контекст:
{c}

Считай, что всю рекламу будет настраивать живой человек, а ты — его умный ассистент.
"""

        schema_hint = """
{
  "overall_approach": [
    "общее объяснение подхода простым языком"
  ],
  "campaign_structure": [
    {
      "channel": "VK | Telegram | блогеры и т.п.",
      "objective": "лиды | заявки | трафик | охваты",
      "layers": [
        {
          "name": "холодный трафик",
          "audience": "пример описания аудитории",
          "formats": ["видео", "баннер", "карточки"],
          "notes": "важные замечания"
        }
      ]
    }
  ],
  "hypotheses": [
    {
      "name": "название гипотезы",
      "segment": "сегмент ЦА",
      "offer": "оффер/предложение",
      "format": "формат креатива",
      "angle": "основная идея захода",
      "expected_metric": "какую метрику хотим улучшить"
    }
  ],
  "testing_plan": {
    "budget_per_hypothesis": "примерный бюджет на одну гипотезу",
    "duration": "ориентировочная длительность теста",
    "stop_rules": [
      "условие остановки 1"
    ],
    "scale_rules": [
      "условие масштабирования 1"
    ]
  }
}
"""

        data = await self.llm_json(instruction, schema_hint)
        return data
