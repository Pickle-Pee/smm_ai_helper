# app/agents/strategy_agent.py
from __future__ import annotations

from typing import Any, Dict, List

from app.agents.qc import qc_block
from .base import BaseAgent
from .utils import normalize_brief


class StrategyAgent(BaseAgent):
    system_prompt = (
        "Ты — старший SMM-стратег для малого и среднего бизнеса.\n"
        "Думаешь в терминах воронки, позиционирования, сегментов и креативной стратегии, "
        "но объясняешь простым языком.\n\n"
        "Правила качества:\n"
        "- Никакой воды и общих фраз. Каждый пункт должен быть конкретным и применимым.\n"
        "- Не выдумывай факты о продукте. Если данных мало — делай допущения и явно помечай их.\n"
        "- Минимизируй вопросы пользователю: лучше предложи 2–3 варианта и напиши, как выбрать.\n"
        "- Добавляй примеры формулировок/тем/офферов.\n"
    )

    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ctx = normalize_brief(brief)
        c = ctx.to_dict()

        qc = qc_block(brief)

        instruction = f"""
Нужно разработать SMM-стратегию для проекта.

Данные брифа (используй всё полезное):
{c}

Требования:
1) Сделай стратегию "сверху-вниз": позиционирование → сегменты → воронка → каналы → контент/офферы → план на 7 дней.
2) Не используй абстракции. Для каждого блока дай примеры:
   - минимум 5 примеров тем/постов
   - минимум 3 примера оффера/CTA (как написать)
   - минимум 5 креативных углов (angle) для рекламы/постов
3) Если в брифе нет ниши/цены/гео — сделай разумные допущения и верни их в assumptions.
4) Не пиши "аудитория 20–40" без оснований: сегменты должны быть основаны на болях/контексте, а не на возрасте.
5) Каналы: если channels не указаны, предложи 1–2 канала и объясни почему.

{qc}
""".strip()

        schema_hint = """
{
  "assumptions": ["..."],
  "summary": {
    "north_star_metric": "главная метрика успеха SMM",
    "main_bullets": ["тезис 1", "тезис 2", "тезис 3"]
  },
  "positioning": {
    "core_message": "одно главное сообщение бренда",
    "utp": ["УТП 1", "УТП 2", "УТП 3"],
    "reasons_to_believe": ["факт/аргумент 1", "факт/аргумент 2"],
    "tone_of_voice": ["как звучим (3-6 правил)"],
    "do_not_say": ["что не говорим (2-5 анти-паттернов)"]
  },
  "segments": [
    {
      "name": "сегмент (по мотивации/контексту, не по возрасту)",
      "short_profile": "кто эти люди и в какой ситуации",
      "pains": ["боль 1", "боль 2"],
      "triggers": ["триггер 1", "триггер 2"],
      "objections": ["возражение 1", "возражение 2"],
      "message_map": {
        "hook_angles": ["угол 1", "угол 2"],
        "proof_points": ["что доказываем", "какие факты нужны"],
        "cta_examples": ["пример CTA 1", "пример CTA 2"]
      }
    }
  ],
  "funnel": {
    "awareness": {
      "goal": "что добиваемся",
      "content_types": ["что публикуем"],
      "examples": ["пример 1", "пример 2"]
    },
    "consideration": {
      "goal": "что добиваемся",
      "content_types": ["что публикуем"],
      "examples": ["пример 1", "пример 2"]
    },
    "conversion": {
      "goal": "что добиваемся",
      "content_types": ["что публикуем"],
      "examples": ["пример 1", "пример 2"]
    },
    "retention": {
      "goal": "что добиваемся",
      "content_types": ["что публикуем"],
      "examples": ["пример 1", "пример 2"]
    }
  },
  "offers": [
    {
      "name": "название оффера",
      "what_user_gets": "что получает человек",
      "for_whom": "для кого",
      "friction_reducers": ["что снимает страх/трение"],
      "cta_examples": ["текст CTA 1", "текст CTA 2"]
    }
  ],
  "channels": [
    {
      "name": "Telegram|Instagram|VK|...",
      "role": "зачем канал в стратегии",
      "cadence": "частота + почему",
      "content_focus": ["что там публикуем"],
      "conversion_path": "как ведем к целевому действию"
    }
  ],
  "content_rubrics": [
    {
      "name": "рубрика",
      "goal": "какую задачу решает",
      "examples": ["пример темы 1", "пример темы 2", "пример темы 3"]
    }
  ],
  "creative_angles": [
    {
      "angle": "креативный угол",
      "when_to_use": "когда подходит",
      "example_headline": "пример заголовка",
      "example_text": "пример текста 2-4 строки"
    }
  ],
  "first_7_days_plan": [
    {
      "day": 1,
      "channel": "канал",
      "format": "пост|сторис|рилс|опрос",
      "topic": "тема",
      "goal": "цель",
      "key_points": ["тезис 1", "тезис 2"],
      "cta": "конкретный CTA"
    }
  ],
  "risks_and_limits": [
    "риск/ограничение",
    "что с ним делать"
  ]
}
"""

        data = await self.llm_json(instruction, schema_hint)

        # Защита от отсутствующих ключей
        data.setdefault("assumptions", [])
        data.setdefault("summary", {})
        data.setdefault("positioning", {})
        data.setdefault("segments", [])
        data.setdefault("channels", [])
        data.setdefault("content_rubrics", [])
        data.setdefault("offers", [])
        data.setdefault("creative_angles", [])
        data.setdefault("first_7_days_plan", [])
        data.setdefault("risks_and_limits", [])

        summary = data.get("summary") or {}
        bullets = summary.get("main_bullets") or []
        if not isinstance(bullets, list):
            bullets = [str(bullets)]

        north_star = summary.get("north_star_metric") or "Целевое действие (уточнить по продукту)"

        summary_text = "Кратко:\n" + "\n".join(f"• {b}" for b in bullets[:5])

        # Более развернутый текст — чтобы не было “скомкано”
        lines: List[str] = []
        lines.append(f"## NORTH STAR метрика\n{north_star}\n")

        if bullets:
            lines.append("## Ключевые тезисы")
            lines.extend([f"- {b}" for b in bullets[:7]])
            lines.append("")

        assumptions = data.get("assumptions") or []
        if assumptions:
            lines.append("## Допущения (из-за неполного брифа)")
            lines.extend([f"- {a}" for a in assumptions[:7]])
            lines.append("")

        positioning = data.get("positioning") or {}
        core = positioning.get("core_message")
        utp = positioning.get("utp") or []
        rtb = positioning.get("reasons_to_believe") or []
        tov = positioning.get("tone_of_voice") or []
        dns = positioning.get("do_not_say") or []

        lines.append("## Позиционирование")
        if core:
            lines.append(f"**Сообщение:** {core}")
        if utp:
            lines.append("\n**УТП:**")
            lines.extend([f"- {u}" for u in utp[:8]])
        if rtb:
            lines.append("\n**Почему поверят:**")
            lines.extend([f"- {x}" for x in rtb[:6]])
        if tov:
            lines.append("\n**TOV (как звучим):**")
            lines.extend([f"- {x}" for x in tov[:6]])
        if dns:
            lines.append("\n**Чего избегаем:**")
            lines.extend([f"- {x}" for x in dns[:6]])
        lines.append("")

        segments = data.get("segments") or []
        if segments:
            lines.append("## Сегменты и сообщения")
            for s in segments[:3]:
                name = s.get("name") or "Сегмент"
                prof = s.get("short_profile") or ""
                pains = s.get("pains") or []
                trig = s.get("triggers") or []
                obj = s.get("objections") or []
                mm = s.get("message_map") or {}
                hooks = mm.get("hook_angles") or []
                ctas = mm.get("cta_examples") or []

                lines.append(f"### {name}")
                if prof:
                    lines.append(prof)
                if pains:
                    lines.append("**Боли:** " + "; ".join([str(x) for x in pains[:4]]))
                if trig:
                    lines.append("**Триггеры:** " + "; ".join([str(x) for x in trig[:4]]))
                if obj:
                    lines.append("**Возражения:** " + "; ".join([str(x) for x in obj[:4]]))
                if hooks:
                    lines.append("**Углы захода:**")
                    lines.extend([f"- {h}" for h in hooks[:4]])
                if ctas:
                    lines.append("**CTA примеры:**")
                    lines.extend([f"- {x}" for x in ctas[:3]])
                lines.append("")

        channels = data.get("channels") or []
        if channels:
            lines.append("## Каналы")
            for ch in channels[:3]:
                name = ch.get("name") or "Канал"
                role = ch.get("role") or ""
                cadence = ch.get("cadence") or ""
                focus = ch.get("content_focus") or []
                path = ch.get("conversion_path") or ""
                lines.append(f"### {name}")
                if role:
                    lines.append(f"- Роль: {role}")
                if cadence:
                    lines.append(f"- Частота: {cadence}")
                if focus:
                    lines.append(f"- Фокус контента: {', '.join([str(x) for x in focus[:6]])}")
                if path:
                    lines.append(f"- Путь к конверсии: {path}")
                lines.append("")

        offers = data.get("offers") or []
        if offers:
            lines.append("## Офферы (что предлагать)")
            for o in offers[:3]:
                name = o.get("name") or "Оффер"
                what = o.get("what_user_gets") or ""
                who = o.get("for_whom") or ""
                fr = o.get("friction_reducers") or []
                ctas = o.get("cta_examples") or []
                lines.append(f"### {name}")
                if what:
                    lines.append(f"- Что получает: {what}")
                if who:
                    lines.append(f"- Для кого: {who}")
                if fr:
                    lines.append("- Снимаем трение: " + "; ".join([str(x) for x in fr[:4]]))
                if ctas:
                    lines.append("- CTA примеры:")
                    lines.extend([f"  - {x}" for x in ctas[:3]])
                lines.append("")

        angles = data.get("creative_angles") or []
        if angles:
            lines.append("## Креативные углы (для рекламы/постов)")
            for a in angles[:5]:
                angle = a.get("angle") or ""
                when = a.get("when_to_use") or ""
                h = a.get("example_headline") or ""
                t = a.get("example_text") or ""
                if angle:
                    lines.append(f"- **{angle}**" + (f" — {when}" if when else ""))
                    if h:
                        lines.append(f"  - Заголовок: {h}")
                    if t:
                        lines.append(f"  - Текст: {t}")
            lines.append("")

        first7 = data.get("first_7_days_plan") or []
        if first7:
            lines.append("## План на первые 7 дней (старт)")
            for it in first7[:7]:
                day = it.get("day")
                ch = it.get("channel") or ""
                fmt = it.get("format") or ""
                topic = it.get("topic") or ""
                goal = it.get("goal") or ""
                cta = it.get("cta") or ""
                kps = it.get("key_points") or []
                lines.append(f"**День {day}** — {ch} / {fmt}")
                if topic:
                    lines.append(f"- Тема: {topic}")
                if goal:
                    lines.append(f"- Цель: {goal}")
                if kps:
                    lines.append("- Тезисы:")
                    lines.extend([f"  - {x}" for x in kps[:5]])
                if cta:
                    lines.append(f"- CTA: {cta}")
                lines.append("")

        risks = data.get("risks_and_limits") or []
        if risks:
            lines.append("## Риски и ограничения")
            lines.extend([f"- {r}" for r in risks[:8]])
            lines.append("")

        full_strategy = "\n".join(lines).strip()

        return {
            "structured": data,
            "summary_text": summary_text,
            "full_strategy": full_strategy,
        }
