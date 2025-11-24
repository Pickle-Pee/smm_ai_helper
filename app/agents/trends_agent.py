# app/agents/trends_agent.py
from typing import Any, Dict

from .base import BaseAgent
from .utils import normalize_brief


class TrendsAgent(BaseAgent):
    system_prompt = (
        "Ты — SMM-специалист, который постоянно сидит в ленте и смотрит,"
        " какие форматы и механики реально залетают."
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        instruction = f"""
Нужно подсветить актуальные тренды и превратить их в понятные для бизнеса эксперименты.

Контекст:
{c}
"""

        schema_hint = """
{
  "format_trends": [
    {
      "format": "Reels | Shorts | Stories | карусели | лонгриды",
      "description": "что сейчас в этом формате работает",
      "suitable_for_brand": true,
      "how_to_use": "как адаптировать для этого бренда"
    }
  ],
  "content_trends": [
    {
      "pattern": "например: честный закулисный контент",
      "description": "в чём суть приёма",
      "risks": ["какие есть риски/ограничения"]
    }
  ],
  "engagement_mechanics": [
    {
      "mechanic": "опросы, квизы, UGC, челленджи",
      "idea_for_brand": "конкретная идея для этого бренда",
      "expected_effect": "чего ждём (ER, охваты, комьюнити)"
    }
  ],
  "experiment_roadmap": [
    {
      "experiment_name": "название мини-эксперимента",
      "hypothesis": "если мы сделаем X, то Y улучшится, потому что Z",
      "format": "формат/канал",
      "how_to_measure": "как понять, что эксперимент успешен"
    }
  ]
}
"""

        data = await self.llm_json(instruction, schema_hint)
        return data
