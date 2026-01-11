# app/agents/analytics_agent.py
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAgent
from .utils import normalize_brief
from app.agents.qc import qc_block


class AnalyticsAgent(BaseAgent):
    system_prompt = (
        "Ты — маркетинговый аналитик по SMM. "
        "Твоя цель — дать практичную аналитику и план действий, а не общие слова.\n\n"
        "Правила:\n"
        "- Пиши конкретно: что проверить, как посчитать, какие выводы возможны.\n"
        "- Не выдумывай цифры и бенчмарки. Если нет данных — укажи диапазон как 'зависит от ниши' "
        "или предложи собрать данные за 7 дней.\n"
        "- Ответ должен быть понятен новичку.\n"
        "- Всегда предлагай 5–10 следующих шагов, которые можно сделать сегодня/на неделе.\n"
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        raw_metrics: Optional[Any] = brief.get("metrics")
        platform = (brief.get("platform") or "").strip()
        goal = (c.get("goals") or "").strip()

        # Встроим QC-замечания (если это повторный прогон)
        qc = qc_block(brief)

        instruction = f"""
Нужно помочь с аналитикой SMM-активностей и дать план, что делать дальше.

Контекст:
{c}

Платформа (если указана): {platform or "не указано"}
Цель (если указана): {goal or "не указано"}

Сырые метрики/описание ситуации (если есть):
{raw_metrics}

Требования к результату:
1) Если метрики ЕСТЬ:
   - Коротко “что видно” (диагноз) и почему это важно.
   - Найди 3–7 гипотез, что может быть причиной проблем/просадок (если они есть).
   - Дай 5–10 конкретных следующих шагов (что изменить в контенте/воронке/оффере/частоте/упаковке).
2) Если метрик НЕТ:
   - Дай минимальный план измерений на 7 дней: что собрать, где взять, как фиксировать.
   - Дай таблицу/шаблон “минимальный отчет” (полями), чтобы человек мог руками вести.
3) Не придумывай точные бенчмарки “хорошо/плохо”, если нет ниши/данных.
   Вместо этого:
   - укажи “зависит от ниши”,
   - предложи сравнивать с собственной базой (неделя к неделе),
   - и/или предложи A/B тест.

{qc}
""".strip()

        schema_hint = """
{
  "has_metrics": true,
  "metrics_plan": [
    {
      "channel": "Telegram",
      "scope": "контент|воронка|реклама",
      "metrics": [
        {
          "name": "ER",
          "how_to_calc": "как посчитать простым языком",
          "data_source": "где взять (Telegram stats/UTM/GA/таблица)",
          "why_important": "что показывает и какой вывод можно сделать",
          "interpretation": "как интерпретировать (если растет/падает)"
        }
      ]
    }
  ],
  "data_missing": [
    "каких данных не хватает, чтобы сделать выводы"
  ],
  "diagnosis": [
    {
      "finding": "что видно по данным или по описанию",
      "why_it_matters": "почему это важно",
      "likely_causes": ["возможная причина 1", "возможная причина 2"]
    }
  ],
  "benchmarks": [
    {
      "metric": "ER",
      "guidance": "без цифр: как сравнивать (с прошлой неделей/между форматами/между рубриками)",
      "notes": "оговорки"
    }
  ],
  "next_steps": [
    {
      "step": "конкретное действие",
      "impact": "ожидаемый эффект",
      "effort": "низкий|средний|высокий",
      "how_to_do": "короткая инструкция"
    }
  ],
  "report_template": {
    "frequency": "ежедневно|еженедельно",
    "fields": ["date", "post_link", "format", "reach", "views", "clicks", "subs", "notes"]
  }
}
"""

        data = await self.llm_json(instruction, schema_hint)

        # Небольшая пост-валидация на случай “кривого” JSON по смыслу
        if "has_metrics" not in data:
            data["has_metrics"] = bool(raw_metrics)

        # Если модель вернула next_steps строками — нормализуем в объектный вид
        if isinstance(data.get("next_steps"), list) and data["next_steps"] and isinstance(data["next_steps"][0], str):
            data["next_steps"] = [
                {"step": s, "impact": "—", "effort": "средний", "how_to_do": "—"} for s in data["next_steps"][:10]
            ]

        return data
