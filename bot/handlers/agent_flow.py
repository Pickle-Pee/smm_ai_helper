# bot/handlers/agent_flow.py
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import httpx

from app.config import settings

router = Router()


class AgentStates(StatesGroup):
    waiting_task_description = State()
    asking_details = State()
    running_agent = State()


AGENT_CONFIG = {
    "agent_strategy": {
        "name": "Стратегия",
        "agent_type": "strategy",
        "questions": [
            ("brand_name", "Как называется проект/бренд?"),
            ("product_description", "Что за продукт/услуга? Опиши в 1–3 предложениях."),
            ("audience", "Кто твоя целевая аудитория?"),
            ("goals", "Какие цели по SMM? (узнаваемость, заявки, продажи, подписчики и т.п.)"),
            ("channels", "Где планируешь вести активность? (Telegram, VK, Instagram и т.п., через запятую)"),
            ("tone", "Какой тон коммуникации ты хочешь? (дружелюбный, экспертный, дерзкий и т.п.)"),
        ],
    },
    "agent_content": {
        "name": "Контент",
        "agent_type": "content",
        "questions": [
            ("brand_name", "Как называется проект/бренд?"),
            ("product_description", "Что за продукт/услуга?"),
            ("audience", "Кто ЦА?"),
            ("channels", "Для каких площадок генерим контент? (через запятую)"),
            ("goal", "Какая цель контента сейчас? (прогрев, охваты, заявки и т.п.)"),
            ("period", "На какой период нужен план? (например: 14)"),
            ("tone", "Какой тон коммуникации хочешь?"),
        ],
    },
    "agent_analytics": {
        "name": "Аналитика",
        "agent_type": "analytics",
        "questions": [
            ("channels", "По каким каналам есть данные?"),
            ("metrics", "Вставь сюда кратко метрики или опиши ситуацию (что просело/выросло)."),
            ("goal", "Что хочешь понять от аналитики?"),
        ],
    },
    "agent_promo": {
        "name": "Продвижение",
        "agent_type": "promo",
        "questions": [
            ("brand_name", "Как называется проект/бренд?"),
            ("product_description", "Что за продукт/услуга?"),
            ("audience", "Кто ЦА?"),
            ("goals", "Какие цели по рекламе? (лиды, заявки, подписчики и т.п.)"),
            ("channels", "Где хочешь запускать рекламу? (VK Ads, TG, блогеры и т.п.)"),
            ("budget", "Какой примерный бюджет на тесты? (можно диапазон)"),
        ],
    },
    "agent_trends": {
        "name": "Тренды",
        "agent_type": "trends",
        "questions": [
            ("product_description", "Кратко опиши продукт/нишу."),
            ("audience", "Кто твоя ЦА?"),
            ("channels", "Какие площадки интересуют?"),
        ],
    },
}


def get_next_question(agent_key: str, answered: dict):
    cfg = AGENT_CONFIG[agent_key]
    for field, text in cfg["questions"]:
        if field not in answered:
            return field, text
    return None, None


# ===========================
# Выбор агента и сбор брифа
# ===========================

@router.callback_query(F.data.in_(AGENT_CONFIG.keys()))
async def choose_agent(callback: CallbackQuery, state: FSMContext):
    agent_key = callback.data
    cfg = AGENT_CONFIG[agent_key]

    await state.update_data(
        agent_key=agent_key,
        agent_type=cfg["agent_type"],
        answers={},
        task_description=None,
    )
    await state.set_state(AgentStates.waiting_task_description)

    await callback.message.edit_text(
        f"Окей, работаем с агентом: <b>{cfg['name']}</b>.\n\n"
        "Опиши, пожалуйста, свою задачу в свободной форме.\n\n"
        "Например: «Нужна стратегия для студии массажа» "
        "или «Сделай контент-план для ТГ-канала про IT»."
    )
    await callback.answer()


@router.message(AgentStates.waiting_task_description)
async def get_task_description(message: types.Message, state: FSMContext):
    await state.update_data(task_description=message.text)

    data = await state.get_data()
    agent_key = data["agent_key"]

    field, question = get_next_question(agent_key, data.get("answers", {}))
    if field is None:
        await run_agent_and_reply(message, state)
        return

    answers = data["answers"]
    answers[field] = None
    await state.update_data(current_field=field, answers=answers)

    await state.set_state(AgentStates.asking_details)
    await message.answer(question)


@router.message(AgentStates.asking_details)
async def ask_details(message: types.Message, state: FSMContext):
    data = await state.get_data()
    agent_key = data["agent_key"]
    answers = data["answers"]
    current_field = data["current_field"]

    answers[current_field] = message.text
    await state.update_data(answers=answers)

    field, question = get_next_question(agent_key, answers)
    if field is None:
        await run_agent_and_reply(message, state)
        return

    await state.update_data(current_field=field)
    await message.answer(question)


# ===========================
# Форматирование ответов агентов
# ===========================

def format_strategy_result(result: dict) -> str:
    """
    StrategyAgent:
    {
      "structured": {...},
      "summary_text": "...",
      "full_strategy": "..."
    }
    """
    summary_text = result.get("summary_text") or ""
    structured = result.get("structured") or {}
    positioning = structured.get("positioning") or {}
    core_msg = positioning.get("core_message") or ""
    utp_list = positioning.get("utp") or []

    lines: list[str] = []

    if summary_text:
        lines.append("<b>Кратко по стратегии:</b>")
        lines.append(summary_text)
        lines.append("")

    if core_msg:
        lines.append("<b>Позиционирование:</b>")
        lines.append(core_msg)
        lines.append("")

    if utp_list:
        lines.append("<b>Ключевые УТП:</b>")
        for u in utp_list[:5]:
            lines.append(f"• {u}")

    return "\n".join(lines)


def format_strategy_full(result: dict) -> str:
    full = result.get("full_strategy") or ""
    structured = result.get("structured") or {}
    segments = structured.get("segments") or []

    lines: list[str] = []
    if full:
        lines.append("<b>Полная стратегия:</b>\n")
        lines.append(full)

    if segments:
        lines.append("\n<b>Сегменты ЦА:</b>")
        for s in segments:
            name = s.get("name")
            prof = s.get("short_profile")
            if not name:
                continue
            lines.append(f"\n<b>{name}</b>")
            if prof:
                lines.append(prof)

    return "\n".join(lines)


def format_content_result_digest(result: dict) -> list[str]:
    """
    digest: только план + первый пост.
    ContentAgent:
    {
      "plan_items": [...],
      "posts": [
        {"plan_item": {...}, "post": {...}}
      ],
      "raw_plan_markdown": "..."
    }
    """
    messages: list[str] = []

    plan_md = result.get("raw_plan_markdown") or ""
    if plan_md:
        messages.append("<b>Контент-план:</b>\n" + plan_md)

    posts = result.get("posts") or []
    if posts:
        first = posts[0]
        post_text = first.get("post", {}).get("full_text") or ""
        if post_text:
            messages.append("<b>Пример поста:</b>\n" + post_text)

    return messages


def format_content_more_posts(result: dict) -> list[str]:
    """
    остальные посты (2,3,...) — по запросу.
    """
    messages: list[str] = []
    posts = result.get("posts") or []

    if len(posts) <= 1:
        return ["Пока дополнительных постов нет — сгенерируй новую задачу, если нужно больше."]

    for idx, p in enumerate(posts[1:], start=2):
        post_text = p.get("post", {}).get("full_text") or ""
        if not post_text:
            continue
        messages.append(f"<b>Пост #{idx}:</b>\n{post_text}")

    return messages or ["Дополнительных постов нет."]


def format_analytics_digest(result: dict) -> list[str]:
    """
    digest: только next_steps.
    AnalyticsAgent:
    {
      "metrics_plan": [...],
      "benchmarks": [...],
      "diagnosis": [...],
      "next_steps": [...]
    }
    """
    messages: list[str] = []
    next_steps = result.get("next_steps") or []
    if next_steps:
        lines = ["<b>Что делать дальше:</b>"]
        for step in next_steps[:10]:
            lines.append(f"• {step}")
        messages.append("\n".join(lines))
    else:
        messages.append("Пока нет явных рекомендаций — попробуй задать задачу чуть конкретнее.")
    return messages


def format_analytics_details(result: dict) -> list[str]:
    messages: list[str] = []

    metrics_plan = result.get("metrics_plan") or []
    if metrics_plan:
        lines = ["<b>Какие метрики смотреть:</b>"]
        for ch in metrics_plan:
            channel = ch.get("channel")
            if channel:
                lines.append(f"\n<b>{channel}:</b>")
            for m in ch.get("metrics", []):
                name = m.get("name")
                why = m.get("why_important")
                how = m.get("how_to_calc")
                line = f"• {name}"
                if why:
                    line += f" — {why}"
                if how:
                    line += f" (как считать: {how})"
                lines.append(line)
        messages.append("\n".join(lines)[:4000])

    benchmarks = result.get("benchmarks") or []
    if benchmarks:
        lines = ["<b>Ориентиры по метрикам (очень грубо):</b>"]
        for b in benchmarks:
            metric = b.get("metric")
            good = b.get("good")
            bad = b.get("bad")
            comment = b.get("comment")
            line = f"• {metric}: хорошо ~ {good}, плохо ~ {bad}"
            if comment:
                line += f" ({comment})"
            lines.append(line)
        messages.append("\n".join(lines)[:4000])

    diagnosis = result.get("diagnosis") or []
    if diagnosis:
        lines = ["<b>Что может быть не так:</b>"]
        for d in diagnosis:
            lines.append(f"• {d}")
        messages.append("\n".join(lines)[:4000])

    return messages or ["Подробных данных по аналитике пока нет."]


def format_promo_digest(result: dict) -> list[str]:
    """
    digest: общий подход + пара гипотез.
    """
    messages: list[str] = []

    overall = result.get("overall_approach") or []
    if overall:
        lines = ["<b>Подход к рекламе:</b>"]
        for l in overall[:5]:
            lines.append(f"• {l}")
        messages.append("\n".join(lines))

    hypotheses = result.get("hypotheses") or []
    if hypotheses:
        lines = ["<b>Пара стартовых гипотез:</b>"]
        for h in hypotheses[:3]:
            name = h.get("name")
            segment = h.get("segment")
            offer = h.get("offer")
            angle = h.get("angle")
            lines.append("")
            if name:
                lines.append(f"<b>{name}</b>")
            if segment:
                lines.append(f"ЦА: {segment}")
            if offer:
                lines.append(f"Оффер: {offer}")
            if angle:
                lines.append(f"Идея: {angle}")
        messages.append("\n".join(lines)[:4000])

    return messages or ["Пока нет идей — попробуй сформулировать задачу чуть конкретнее."]


def format_promo_details(result: dict) -> list[str]:
    messages: list[str] = []

    campaigns = result.get("campaign_structure") or []
    if campaigns:
        lines = ["<b>Структура кампаний:</b>"]
        for c in campaigns:
            channel = c.get("channel")
            obj = c.get("objective")
            if channel:
                lines.append(f"\n<b>{channel}</b> (цель: {obj})")
            for layer in c.get("layers", []):
                name = layer.get("name")
                aud = layer.get("audience")
                formats = layer.get("formats")
                notes = layer.get("notes")
                if name:
                    lines.append(f"— {name}")
                if aud:
                    lines.append(f"  ЦА: {aud}")
                if formats:
                    lines.append(f"  Форматы: {', '.join(formats)}")
                if notes:
                    lines.append(f"  Заметки: {notes}")
        messages.append("\n".join(lines)[:4000])

    testing = result.get("testing_plan") or {}
    if testing:
        lines = ["<b>Как тестировать:</b>"]
        budget = testing.get("budget_per_hypothesis")
        duration = testing.get("duration")
        if budget:
            lines.append(f"Бюджет на гипотезу: {budget}")
        if duration:
            lines.append(f"Длительность теста: {duration}")
        stop_rules = testing.get("stop_rules") or []
        if stop_rules:
            lines.append("\nСтоп-правила:")
            for r in stop_rules:
                lines.append(f"• {r}")
        scale_rules = testing.get("scale_rules") or []
        if scale_rules:
            lines.append("\nМасштабирование:")
            for r in scale_rules:
                lines.append(f"• {r}")
        messages.append("\n".join(lines)[:4000])

    return messages or ["Подробного плана тестов пока нет."]


def format_trends_digest(result: dict) -> list[str]:
    """
    digest: только experiment_roadmap.
    """
    messages: list[str] = []

    exp = result.get("experiment_roadmap") or []
    if exp:
        lines = ["<b>Эксперименты, которые можно запустить:</b>"]
        for e in exp[:5]:
            name = e.get("experiment_name")
            hyp = e.get("hypothesis")
            fmt = e.get("format")
            lines.append("")
            if name:
                lines.append(f"<b>{name}</b>")
            if fmt:
                lines.append(f"Формат: {fmt}")
            if hyp:
                lines.append(f"Гипотеза: {hyp}")
        messages.append("\n".join(lines)[:4000])
    else:
        messages.append("Пока нет явных идей для экспериментов — попробуй уточнить нишу или формат.")

    return messages


def format_trends_details(result: dict) -> list[str]:
    messages: list[str] = []

    fmt_trends = result.get("format_trends") or []
    if fmt_trends:
        lines = ["<b>Форматные тренды:</b>"]
        for t in fmt_trends[:5]:
            fmt = t.get("format")
            desc = t.get("description")
            how_use = t.get("how_to_use")
            lines.append("")
            if fmt:
                lines.append(f"<b>{fmt}</b>")
            if desc:
                lines.append(desc)
            if how_use:
                lines.append(f"Как использовать: {how_use}")
        messages.append("\n".join(lines)[:4000])

    content_trends = result.get("content_trends") or []
    if content_trends:
        lines = ["<b>Сюжетные тренды:</b>"]
        for ct in content_trends[:5]:
            pattern = ct.get("pattern")
            desc = ct.get("description")
            risks = ct.get("risks") or []
            lines.append("")
            if pattern:
                lines.append(f"<b>{pattern}</b>")
            if desc:
                lines.append(desc)
            if risks:
                lines.append("Риски:")
                for r in risks:
                    lines.append(f"• {r}")
        messages.append("\n".join(lines)[:4000])

    mechanics = result.get("engagement_mechanics") or []
    if mechanics:
        lines = ["<b>Механики вовлечения:</b>"]
        for m in mechanics[:5]:
            mech = m.get("mechanic")
            idea = m.get("idea_for_brand")
            eff = m.get("expected_effect")
            lines.append("")
            if mech:
                lines.append(f"<b>{mech}</b>")
            if idea:
                lines.append(f"Идея: {idea}")
            if eff:
                lines.append(f"Что даёт: {eff}")
        messages.append("\n".join(lines)[:4000])

    return messages or ["Подробных трендов пока нет."]


# ===========================
# Клавиатуры “Показать подробнее”
# ===========================

def kb_strategy_more(task_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Показать полную стратегию", callback_data=f"strategy_full:{task_id}")
    kb.adjust(1)
    return kb.as_markup()


def kb_content_more(task_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Показать остальные посты", callback_data=f"content_more:{task_id}")
    kb.adjust(1)
    return kb.as_markup()


def kb_analytics_more(task_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Показать детали аналитики", callback_data=f"analytics_more:{task_id}")
    kb.adjust(1)
    return kb.as_markup()


def kb_promo_more(task_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Показать структуру кампаний", callback_data=f"promo_more:{task_id}")
    kb.adjust(1)
    return kb.as_markup()


def kb_trends_more(task_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Подробнее про тренды", callback_data=f"trends_more:{task_id}")
    kb.adjust(1)
    return kb.as_markup()


# ===========================
# Запуск агента и первичный ответ
# ===========================

async def run_agent_and_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    agent_type: str = data["agent_type"]
    agent_key: str = data["agent_key"]
    answers: dict = data["answers"]
    task_description: str = data["task_description"]

    await state.set_state(AgentStates.running_agent)
    await message.answer("Обрабатываю задачу, дай немного времени 🤖...")

    payload = {
        "user": {
            "telegram_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
        },
        "agent_type": agent_type,
        "task_description": task_description,
        "answers": answers,
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{settings.API_BASE_URL}/agents/{agent_type}/run",
            json=payload,
        )
        if resp.status_code >= 400:
            await state.clear()
            await message.answer(
                "Произошла ошибка при выполнении задачи. Попробуй ещё раз позже."
            )
            return
        data_resp = resp.json()

    await state.clear()

    task_id = data_resp["task_id"]
    result = data_resp["result"]

    # Для каждого агента — свой дайджест + кнопка "подробнее"
    if agent_key == "agent_strategy":
        text = format_strategy_result(result)
        await message.answer(text[:4000], reply_markup=kb_strategy_more(task_id))

    elif agent_key == "agent_content":
        msgs = format_content_result_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await message.answer(txt[:4000], reply_markup=kb_content_more(task_id))
            else:
                await message.answer(txt[:4000])

    elif agent_key == "agent_analytics":
        msgs = format_analytics_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await message.answer(txt[:4000], reply_markup=kb_analytics_more(task_id))
            else:
                await message.answer(txt[:4000])

    elif agent_key == "agent_promo":
        msgs = format_promo_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await message.answer(txt[:4000], reply_markup=kb_promo_more(task_id))
            else:
                await message.answer(txt[:4000])

    elif agent_key == "agent_trends":
        msgs = format_trends_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await message.answer(txt[:4000], reply_markup=kb_trends_more(task_id))
            else:
                await message.answer(txt[:4000])


# ===========================
# Callback’и “Показать подробнее”
# ===========================

async def fetch_task_result(task_id: int) -> dict | None:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"{settings.API_BASE_URL}/tasks/{task_id}")
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data.get("result")


@router.callback_query(F.data.startswith("strategy_full:"))
async def on_strategy_full(callback: CallbackQuery):
    _, task_id_str = callback.data.split(":", 1)
    task_id = int(task_id_str)
    result = await fetch_task_result(task_id)
    if not result:
        await callback.answer("Не удалось получить стратегию 😔", show_alert=True)
        return
    text = format_strategy_full(result)
    await callback.message.answer(text[:4000])
    await callback.answer()


@router.callback_query(F.data.startswith("content_more:"))
async def on_content_more(callback: CallbackQuery):
    _, task_id_str = callback.data.split(":", 1)
    task_id = int(task_id_str)
    result = await fetch_task_result(task_id)
    if not result:
        await callback.answer("Не удалось получить контент 😔", show_alert=True)
        return
    msgs = format_content_more_posts(result)
    for txt in msgs:
        await callback.message.answer(txt[:4000])
    await callback.answer()


@router.callback_query(F.data.startswith("analytics_more:"))
async def on_analytics_more(callback: CallbackQuery):
    _, task_id_str = callback.data.split(":", 1)
    task_id = int(task_id_str)
    result = await fetch_task_result(task_id)
    if not result:
        await callback.answer("Не удалось получить аналитику 😔", show_alert=True)
        return
    msgs = format_analytics_details(result)
    for txt in msgs:
        await callback.message.answer(txt[:4000])
    await callback.answer()


@router.callback_query(F.data.startswith("promo_more:"))
async def on_promo_more(callback: CallbackQuery):
    _, task_id_str = callback.data.split(":", 1)
    task_id = int(task_id_str)
    result = await fetch_task_result(task_id)
    if not result:
        await callback.answer("Не удалось получить данные по рекламе 😔", show_alert=True)
        return
    msgs = format_promo_details(result)
    for txt in msgs:
        await callback.message.answer(txt[:4000])
    await callback.answer()


@router.callback_query(F.data.startswith("trends_more:"))
async def on_trends_more(callback: CallbackQuery):
    _, task_id_str = callback.data.split(":", 1)
    task_id = int(task_id_str)
    result = await fetch_task_result(task_id)
    if not result:
        await callback.answer("Не удалось получить тренды 😔", show_alert=True)
        return
    msgs = format_trends_details(result)
    for txt in msgs:
        await callback.message.answer(txt[:4000])
    await callback.answer()
