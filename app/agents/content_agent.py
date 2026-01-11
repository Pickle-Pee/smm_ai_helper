# app/agents/content_agent.py
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from app.agents.qc import qc_block
from .base import BaseAgent
from .utils import normalize_brief


class ContentAgent(BaseAgent):
    system_prompt = (
        "Ты — сильный SMM-копирайтер и контент-стратег.\n"
        "Пишешь живо и понятно, без канцелярита, инфобизнес-воды и общих слов.\n"
        "Всегда даёшь конкретику: что сказать, как сказать, каким углом зайти, какой CTA.\n"
        "Если данных мало — делаешь разумные допущения и помечаешь их как предположения.\n"
    )

    def _pick_channels(self, ctx_dict: Dict[str, Any]) -> List[str]:
        ch = ctx_dict.get("channels") or []
        if isinstance(ch, list) and ch:
            return [str(x) for x in ch if str(x).strip()]
        # дефолт
        return ["Telegram"]

    async def build_plan(self, ctx_dict: Dict[str, Any], days: int, qc: str = "") -> List[Dict[str, Any]]:
        start_date = date.today()
        end_date = start_date + timedelta(days=days)

        channels = self._pick_channels(ctx_dict)
        # чтобы не раздувать стоимость — если период длинный, снижаем частоту
        cadence_note = ""
        if days > 21:
            cadence_note = (
                "\nВажно: период длинный. Делай в среднем 3–4 публикации в неделю на канал, "
                "а не каждый день. Расставь даты равномерно.\n"
            )

        instruction = f"""
Нужно составить контент-план, который реально работает: прогревает, объясняет ценность, приводит к действию.

Контекст:
{ctx_dict}

Каналы: {channels}
Период: {start_date} — {end_date} (включительно). Дней: {days}.
{cadence_note}

Требования:
- Баланс воронки: awareness/consideration/conversion/retention (или холодный/тёплый/горячий/retention).
- Баланс рубрик: экспертка, сторителлинг, соц.доказательства, офферы, лёгкое/развлекательное (без кринжа).
- Каждый пост должен иметь:
  1) понятную цель
  2) “угол”/hook (с чего начать)
  3) ключевые тезисы (3–5 пунктов)
  4) CTA-тип (подписка/коммент/переход/заявка/сохранение/опрос)

Ограничения:
- Не используй общие фразы типа “повышаем узнаваемость”.
- Темы должны быть привязаны к продукту/нише из контекста.
- Если чего-то не хватает — сделай предположение, но не задавай вопросы (это не чат).

{qc}
""".strip()

        schema_hint = """
[
  {
    "date": "YYYY-MM-DD",
    "channel": "Telegram|Instagram|VK|...",
    "format": "пост|сторис|рилс|карусель|опрос|шорт",
    "content_type": "экспертный|сторителлинг|оффер|UGC|развлекательный|соцдоказательство",
    "funnel_stage": "awareness|consideration|conversion|retention",
    "rubric": "название рубрики",
    "topic": "тема поста",
    "goal": "охваты|доверие|клики|заявки|продажи|вовлечение|удержание",
    "hook": "первая фраза/угол захода",
    "promise": "что человек получит от поста",
    "key_points": ["пункт 1", "пункт 2", "пункт 3"],
    "cta_type": "comment|save|click|dm|subscribe|poll",
    "cta": "конкретный призыв к действию"
  }
]
"""
        data = await self.llm_json(instruction, schema_hint)
        # на всякий случай: если модель вернула не список
        if not isinstance(data, list):
            return []
        return data

    async def generate_post(self, ctx_dict: Dict[str, Any], item: Dict[str, Any], qc: str = "") -> Dict[str, Any]:
        # небольшая адаптация длины под формат
        fmt = (item.get("format") or "пост").lower()
        length_hint = "400–900 символов"
        if "сторис" in fmt:
            length_hint = "3–5 сторис-экранов (короткие фразы/буллеты)"
        elif "рилс" in fmt or "шорт" in fmt:
            length_hint = "сценарий на 20–35 секунд"

        instruction = f"""
Напиши контент по плану. Важно: текст должен быть конкретным и полезным, без воды.

Контекст:
{ctx_dict}

План:
{item}

Требования:
- Используй hook из плана (можешь усилить).
- Дай 1–2 конкретных примера/формулировки (если уместно).
- Структура: hook → основная мысль → 3–5 тезисов → CTA.
- Длина: {length_hint}.
- Если это оффер — добавь чёткое предложение и следующий шаг.
- Хэштеги: только если действительно уместно, 0–6 штук.

{qc}
""".strip()

        schema_hint = """
{
  "title": "Заголовок (для поста) или короткая тема",
  "hook": "1-2 строки захода",
  "body": "основной контент (абзацы/буллеты)",
  "cta": "призыв к действию (конкретный)",
  "hashtags": ["#пример"],
  "notes_for_design": ["подсказка для визуала (если уместно)"]
}
"""
        data = await self.llm_json(instruction, schema_hint)

        title = (data.get("title") or "").strip()
        hook = (data.get("hook") or "").strip()
        body = (data.get("body") or "").strip()
        cta = (data.get("cta") or "").strip()

        hashtags = data.get("hashtags") or []
        if not isinstance(hashtags, list):
            hashtags = []
        hashtags = [str(x).strip() for x in hashtags if str(x).strip()][:6]

        # Собираем full_text безопасно
        chunks: List[str] = []
        if title:
            chunks.append(title)
        if hook:
            chunks.append(hook)
        if body:
            chunks.append(body)
        if cta:
            chunks.append(cta)
        if hashtags:
            chunks.append(" ".join(hashtags))

        data["full_text"] = "\n\n".join(chunks).strip()
        return data

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        ctx_dict = ctx.to_dict()

        qc = qc_block(brief)

        days = int(kwargs.get("days", 14))
        days = max(3, min(days, 60))  # защита от крайностей

        plan_items = await self.build_plan(ctx_dict, days, qc=qc)

        # экономия: материализуем не всегда 3
        # можно переопределять из brief: variants/materialize_count
        materialize_count = brief.get("materialize_count")
        try:
            materialize_count = int(materialize_count) if materialize_count is not None else None
        except Exception:
            materialize_count = None
        if materialize_count is None:
            materialize_count = 2 if days > 14 else 3

        to_materialize = plan_items[: min(len(plan_items), materialize_count)]
        posts: List[Dict[str, Any]] = []
        for item in to_materialize:
            post_data = await self.generate_post(ctx_dict, item, qc=qc)
            posts.append({"plan_item": item, "post": post_data})

        # Markdown-таблица для вывода в чат (план)
        def sanitize(value: Any) -> str:
            return str(value or "").replace("|", "¦")

        header = (
            "| Дата | Канал | Тип | Формат | Этап | Рубрика | Тема | Цель |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |"
        )
        rows = [
            "| {date} | {channel} | {type_} | {format_} | {stage} | {rubric} | {topic} | {goal} |".format(
                date=sanitize(item.get("date")),
                channel=sanitize(item.get("channel")),
                type_=sanitize(item.get("content_type") or item.get("type")),
                format_=sanitize(item.get("format")),
                stage=sanitize(item.get("funnel_stage")),
                rubric=sanitize(item.get("rubric")),
                topic=sanitize(item.get("topic")),
                goal=sanitize(item.get("goal")),
            )
            for item in plan_items
        ]
        raw_plan_markdown = "\n".join([header, *rows])

        return {
            "plan_items": plan_items,
            "posts": posts,
            "raw_plan_markdown": raw_plan_markdown,
        }
