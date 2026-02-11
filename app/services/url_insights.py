from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.agents.utils import safe_json_parse

URL_INSIGHTS_SYSTEM = """Ты — маркетинговый аналитик. 
Тебе дают краткие извлечения из ссылок (url_summaries): заголовки, мета, CTA, кусок текста и предупреждения.

Если по Instagram стоит предупреждение platform_may_block_scraping или empty_main_text:
- НЕ делай выводы о ЦА по контенту.
- Добавь в questions_to_user просьбу прислать IG_INSIGHTS одним сообщением по шаблону ниже:

IG_INSIGHTS
@аккаунт: @username
цель: продажи | лиды | подписчики | бренд
ниша/продукт: ...
гео: ...
язык: ...

подписчики: ...
ср.охват поста: ...
ср.охват рилс: ...

аудитория (если есть): ...
возраст топ-3: ...
топ-гео: ...

топ-5 контента (тема — охват — сохранения — комментарии):
1) ...
2) ...
3) ...
4) ...
5) ...

ссылки/воронка: ...
средний чек: ...


Задача:
1) Для каждой ссылки сделать практичный маркетинговый разбор: оффер, ЦА, УТП, возражения, CTA, воронка, сильные/слабые места.
2) Если данных недостаточно (например, social platform block) — явно указать, какие данные нужны, и сформировать короткие вопросы пользователю.
3) Дать конкретные рекомендации по улучшению (в приоритете то, что даст быстрый рост конверсии/подписок).
4) Не выдумывай факты. Если чего-то нет — пиши "недостаточно данных".

Вывод строго JSON (без markdown, без пояснений).
"""

URL_INSIGHTS_SCHEMA = {
    "type": "json_schema",
    "name": "url_insights",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "overall": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "brand_guess": {"type": ["string", "null"]},
                    "niche_guess": {"type": ["string", "null"]},
                    "main_offer": {"type": ["string", "null"]},
                    "target_audience": {"type": ["string", "null"]},
                    "key_pains": {"type": "array", "items": {"type": "string"}},
                    "key_benefits": {"type": "array", "items": {"type": "string"}},
                    "funnel_guess": {"type": "array", "items": {"type": "string"}},
                    "top_recommendations": {"type": "array", "items": {"type": "string"}},
                    "risks_or_unknowns": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "brand_guess",
                    "niche_guess",
                    "main_offer",
                    "target_audience",
                    "key_pains",
                    "key_benefits",
                    "funnel_guess",
                    "top_recommendations",
                    "risks_or_unknowns",
                ],
            },
            "per_url": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "url": {"type": "string"},
                        "page_type": {"type": "string"},
                        "ok": {"type": "boolean"},
                        "what_it_is": {"type": ["string", "null"]},
                        "offer": {"type": ["string", "null"]},
                        "cta_found": {"type": "array", "items": {"type": "string"}},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "weaknesses": {"type": "array", "items": {"type": "string"}},
                        "quick_wins": {"type": "array", "items": {"type": "string"}},
                        "missing_data": {"type": "array", "items": {"type": "string"}},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "url",
                        "page_type",
                        "ok",
                        "what_it_is",
                        "offer",
                        "cta_found",
                        "strengths",
                        "weaknesses",
                        "quick_wins",
                        "missing_data",
                        "warnings",
                    ],
                },
            },
            "questions_to_user": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["overall", "per_url", "questions_to_user"],
    },
}


def _minimal_url_payload(url_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in (url_summaries or [])[:3]:
        if not isinstance(s, dict):
            continue

        tg_posts = (s.get("telegram_last_posts") or [])[:5]
        tg_posts = [str(p)[:800] for p in tg_posts]

        out.append(
            {
                "url": s.get("final_url") or s.get("url"),
                "page_type": s.get("page_type"),
                "ok": bool(s.get("ok")),
                "title": s.get("title"),
                "meta_description": s.get("meta_description"),
                "h1": s.get("h1"),
                "headings": s.get("headings"),
                "cta_texts": s.get("cta_texts"),
                "main_text_excerpt": (s.get("main_text_excerpt") or "")[:2500],
                "telegram_last_posts": tg_posts,
                "warnings": s.get("warnings") or [],
                "status_code": s.get("status_code"),
            }
        )
    return out


async def build_url_insights(
    user_message: str,
    url_summaries: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(url_summaries, list) or not url_summaries:
        return None

    payload = {
        "user_message": user_message,
        "url_summaries": _minimal_url_payload(url_summaries),
    }

    messages = [
        {"role": "system", "content": URL_INSIGHTS_SYSTEM},
        {"role": "user", "content": "INPUT_JSON:\n" + json.dumps(payload, ensure_ascii=False)},
    ]

    content, _usage = await openai_chat(
        messages=messages,
        model=settings.DEFAULT_TEXT_MODEL_LIGHT,
        temperature=None,
        response_format=URL_INSIGHTS_SCHEMA,
        task="url_insights_json",
    )

    data = safe_json_parse(content)
    if isinstance(data, dict):
        return data
    return None
