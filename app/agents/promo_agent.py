# app/agents/promo_agent.py
from __future__ import annotations

from typing import Any, Dict, List

from app.agents.qc import qc_block
from .base import BaseAgent
from .utils import normalize_brief


class PromoAgent(BaseAgent):
    system_prompt = (
        "Ты — медиабаер и перформанс-маркетолог.\n"
        "Фокус: гипотезы, тесты, чёткие настройки и правила принятия решений.\n\n"
        "Правила:\n"
        "- Пиши конкретно: сегмент → оффер → креативный угол → формат → что меряем → критерии стоп/скейл.\n"
        "- Не выдумывай точные цены/CPM/CPC. Если бюджета/ниши нет — давай диапазон или методику расчёта.\n"
        "- Минимизируй вопросы пользователю: делай разумные допущения и помечай их.\n"
        "- Избегай воды и общих слов типа 'повысим узнаваемость'.\n"
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        # доп. поля (если есть)
        platform = brief.get("platform") or (c.get("channels")[0] if c.get("channels") else "")
        budget = c.get("budget") or brief.get("budget")
        geo = c.get("geo") or brief.get("geo")
        goal = c.get("goals") or brief.get("goal")

        qc = qc_block(brief)

        instruction = f"""
Нужно предложить структуру платного продвижения и список рекламных гипотез.

Контекст:
{c}

Дополнительные вводные (если есть):
- Площадка/канал фокуса: {platform or "не указано"}
- Гео: {geo or "не указано"}
- Бюджет: {budget or "не указано"}
- Цель: {goal or "не указано"}

Условия:
- Считай, что рекламу настраивает живой специалист, а ты — ассистент, который даёт понятный план.
- Если данных мало — сделай допущения и верни их в assumptions.
- Дай 8–12 гипотез, но не одинаковых: разные сегменты/офферы/углы/форматы.
- Для VK/Telegram/блогеров предложи структуры, релевантные каналу.
- В testing_plan дай практические stop/scale правила без “магических” цифр:
  например через минимальную статистику (клики/лиды) и сравнение к baseline.

{qc}
""".strip()

        schema_hint = """
{
  "assumptions": [
    "какие допущения сделал и почему"
  ],
  "overall_approach": [
    "2-6 коротких принципов, как тестируем и как принимаем решения"
  ],
  "campaign_structure": [
    {
      "channel": "VK|Telegram|bloggers|meta|google|yandex|other",
      "objective": "leads|sales|traffic|reach",
      "tracking": {
        "utm": true,
        "pixel": "что поставить (если применимо)",
        "events": ["lead", "purchase", "subscribe", "click"]
      },
      "layers": [
        {
          "name": "cold|warm|hot|retention",
          "audience": "конкретный сегмент (интересы/поведение/контекст)",
          "exclusions": ["кого исключить"],
          "formats": ["video", "static", "carousel", "native_post"],
          "offer_type": "leadmagnet|discount|trial|demo|content",
          "creative_notes": [
            "1-3 подсказки по креативу (что показать/какие слова/какой первый кадр)"
          ],
          "landing_next_step": "куда ведем и что там должно быть (1-2 предложения)"
        }
      ]
    }
  ],
  "hypotheses": [
    {
      "name": "кратко и по делу",
      "segment": "кто именно (не общими словами)",
      "problem_trigger": "какая боль/триггер",
      "offer": "конкретный оффер/обещание",
      "format": "video|static|carousel|ugc|native",
      "angle": "основной угол (как формулируем)",
      "example_creative": {
        "headline": "пример заголовка",
        "primary_text": "пример текста 2-4 строки",
        "cta": "Записаться|Скачать|Узнать|Написать"
      },
      "expected_metric": "CTR|CPC|CPA|CVR|CPL",
      "success_criteria": "что считаем успехом (качественно или через baseline)",
      "failure_criteria": "что считаем провалом (качественно или через baseline)"
    }
  ],
  "testing_plan": {
    "budget_split": "как делим бюджет (например 60% cold, 30% warm, 10% hot) или по гипотезам",
    "budget_per_hypothesis": "если нет бюджета — предложи формулу (например N кликов/лидов на гипотезу)",
    "duration": "обычно 3-7 дней или до набора минимальной статистики",
    "minimum_data": {
      "clicks": "минимум кликов на гипотезу до вывода (например 100-300) или 'зависит'",
      "leads": "минимум лидов до вывода (например 10-30) или 'зависит'"
    },
    "stop_rules": [
      "конкретное правило остановки (например 'нет кликов при X показах' / 'CPA хуже baseline на Y% после N лидов')"
    ],
    "scale_rules": [
      "конкретное правило масштабирования (например 'CPA лучше baseline и стабильный CTR → увеличиваем бюджет на 20% каждые 2 дня')"
    ],
    "notes": [
      "важные замечания по креативам/модерации/частоте/выгоранию"
    ]
  }
}
"""

        data = await self.llm_json(instruction, schema_hint)

        # базовая нормализация, чтобы downstream не падал
        data.setdefault("assumptions", [])
        data.setdefault("overall_approach", [])
        data.setdefault("campaign_structure", [])
        data.setdefault("hypotheses", [])
        data.setdefault("testing_plan", {})

        return data
