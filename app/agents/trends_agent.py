# app/agents/trends_agent.py
from __future__ import annotations

from typing import Any, Dict, List

from app.agents.qc import qc_block
from .base import BaseAgent
from .utils import normalize_brief


class TrendsAgent(BaseAgent):
    system_prompt = (
        "Ты — SMM-специалист, который следит за тем, какие форматы и механики реально заходят.\n"
        "Но ты не выдаёшь 'новости трендов' как из тиктока — ты превращаешь паттерны в конкретные эксперименты для бизнеса.\n\n"
        "Правила:\n"
        "- Не перечисляй банальности. Всё должно быть привязано к продукту/аудитории/каналам из брифа.\n"
        "- Не говори 'сейчас в тренде X' без смысла: вместо этого формулируй как проверяемый паттерн.\n"
        "- Для каждого паттерна дай: когда подходит, как адаптировать, риск, и как измерить.\n"
        "- Минимизируй вопросы пользователю: делай допущения и помечай их.\n"
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        qc = qc_block(brief)

        # Подсказка: используем каналы из брифа, иначе предлагаем 1-2 по умолчанию
        channels = c.get("channels") or []
        if not channels:
            channels = ["Telegram"]

        instruction = f"""
Нужно подсветить актуальные контент-паттерны/механики и превратить их в понятные эксперименты для бизнеса.

Контекст:
{c}

Каналы фокуса: {channels}

Требования:
1) Не "новости трендов", а ПАТТЕРНЫ (что обычно работает сейчас и почему).
2) Всё адаптируй под бренд: темы, углы, механики, примеры формулировок.
3) Дай 6–10 экспериментов. Каждый эксперимент:
   - гипотеза (если сделаем X → улучшится Y потому что Z)
   - шаги запуска (2–5 шагов)
   - срок (например 7 дней)
   - как измерить (baseline, метрика, критерий успеха)
4) Добавь блок "что НЕ делать" (частые ошибки/кринж/риски для бренда).
5) Если данных мало — сделай допущения и верни их в assumptions.

{qc}
""".strip()

        schema_hint = """
{
  "assumptions": ["..."],
  "format_trends": [
    {
      "format": "Reels|Shorts|Stories|карусель|лонгрид|лайв|подкаст|пост",
      "pattern": "паттерн: что именно работает внутри формата",
      "why_it_works": "почему это цепляет людей (1-2 предложения)",
      "suitable_for_brand": true,
      "how_to_use": "как адаптировать под этот бренд",
      "example_ideas": ["идея 1", "идея 2", "идея 3"],
      "measurement": {
        "primary_metric": "охват|удержание|ER|CTR|подписки",
        "success_signal": "какой сигнал будет означать, что зашло"
      }
    }
  ],
  "content_trends": [
    {
      "pattern": "контент-паттерн (например: 'разбор ошибок')",
      "description": "в чём суть",
      "fit_for_brand": "почему подходит/не подходит",
      "examples_for_brand": ["пример темы 1", "пример темы 2"],
      "risks": ["риск 1", "риск 2"],
      "mitigation": ["как снизить риск 1", "как снизить риск 2"]
    }
  ],
  "engagement_mechanics": [
    {
      "mechanic": "опрос|квиз|UGC|челлендж|рубрика|мини-сериал",
      "idea_for_brand": "конкретная идея для этого бренда",
      "script": "как провести (2-5 шагов)",
      "expected_effect": "что ожидаем улучшить",
      "measurement": "как измерить (метрика + критерий)"
    }
  ],
  "experiment_roadmap": [
    {
      "experiment_name": "название",
      "hypothesis": "если мы сделаем X, то Y улучшится, потому что Z",
      "channel": "канал",
      "format": "формат",
      "steps": ["шаг 1", "шаг 2", "шаг 3"],
      "duration_days": 7,
      "how_to_measure": {
        "baseline": "с чем сравниваем (прошлая неделя/среднее 5 постов/контрольная рубрика)",
        "primary_metric": "метрика",
        "success_criteria": "условие успеха",
        "stop_criteria": "когда останавливаем"
      }
    }
  ],
  "do_not_do": [
    "что не делать (ошибка/антипаттерн) и почему"
  ]
}
"""

        data = await self.llm_json(instruction, schema_hint)

        # лёгкая нормализация
        data.setdefault("assumptions", [])
        data.setdefault("format_trends", [])
        data.setdefault("content_trends", [])
        data.setdefault("engagement_mechanics", [])
        data.setdefault("experiment_roadmap", [])
        data.setdefault("do_not_do", [])

        # подстрахуем duration_days
        exp = data.get("experiment_roadmap") or []
        if isinstance(exp, list):
            for e in exp:
                if isinstance(e, dict) and not isinstance(e.get("duration_days"), int):
                    e["duration_days"] = 7

        return data
