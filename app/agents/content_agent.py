# app/agents/content_agent.py
from datetime import date, timedelta
from typing import Any, Dict, List

from .base import BaseAgent
from .utils import normalize_brief


class ContentAgent(BaseAgent):
    system_prompt = (
        "Ты — сильный SMM-копирайтер и контент-стратег. "
        "Умеешь держать баланс рубрик и этапов воронки, пишешь живыми, "
        "понятными текстами без канцелярита и инфобизнес-воды."
    )

    async def build_plan(self, ctx_dict: Dict[str, Any], days: int) -> List[Dict[str, Any]]:
        start_date = date.today()
        end_date = start_date + timedelta(days=days)

        instruction = f"""
Нужно составить контент-план, который не превращается в унылую ленту, а реально работает.

Контекст:
{ctx_dict}

Период: с {start_date} по {end_date} (включительно).
Количество дней: {days}

Сделай список постов, где:
- есть баланс по этапам воронки (холодный/тёплый/горячий/retention),
- есть сочетание экспертки, сторителлинга, соц.доказательств, офферов и лёгкого развлекательного,
- для каждого поста понятно, зачем он.
"""

        schema_hint = """
[
  {
    "date": "YYYY-MM-DD",
    "channel": "Telegram",
    "type": "экспертный | сторителлинг | оффер | UGC | развлекательный | триггерный",
    "format": "пост | сторис | рилс | карусель | опрос",
    "funnel_stage": "холодный | тёплый | горячий | retention",
    "rubric": "Название рубрики (например: 'ошибки', 'кейсы', 'закулисье')",
    "topic": "Краткое описание темы",
    "goal": "охваты | доверие | заявки | удержание | вовлечение"
  }
]
"""
        data = await self.llm_json(instruction, schema_hint)
        return data

    async def generate_post(self, ctx_dict: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
        instruction = f"""
Нужно написать пост по плану.

Контекст:
{ctx_dict}

Планируемый пост:
{item}

Пиши по-деловому, но живо, без инфостиля и воды.
"""

        schema_hint = """
{
  "title": "Заголовок до 80 символов",
  "lead": "1-2 предложения захода, чтобы зацепить",
  "body": "Основной текст 400-800 символов, разбитый на абзацы",
  "cta": "Призыв к действию (если уместно) или мягкое завершение",
  "hashtags": ["#пример1", "#пример2"]
}
"""
        data = await self.llm_json(instruction, schema_hint)
        full_text = f"{data['title']}\n\n{data['lead']}\n\n{data['body']}\n\n{data['cta']}\n\n" + " ".join(
            data["hashtags"]
        )
        data["full_text"] = full_text
        return data

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        ctx_dict = ctx.to_dict()

        days = int(kwargs.get("days", 14))
        plan_items = await self.build_plan(ctx_dict, days)

        # На первом шаге детализируем первые 3 поста (для скорости/экономии)
        to_materialize = plan_items[: min(len(plan_items), 3)]
        posts: List[Dict[str, Any]] = []
        for item in to_materialize:
            post_data = await self.generate_post(ctx_dict, item)
            posts.append({"plan_item": item, "post": post_data})

        # Markdown-таблица для вывода в чат
        header = "| Дата | Канал | Тип | Формат | Этап | Рубрика | Тема | Цель |\n|---|---|---|---|---|---|---|---|"
        rows = [
            f"| {i['date']} | {i['channel']} | {i['type']} | {i['format']} | {i['funnel_stage']} | {i['rubric']} | {i['topic']} | {i['goal']} |"
            for i in plan_items
        ]
        raw_plan_markdown = "\n".join([header, *rows])

        return {
            "plan_items": plan_items,
            "posts": posts,
            "raw_plan_markdown": raw_plan_markdown,
        }
