# bot/handlers/agent_flow.py
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import httpx

from app.config import settings
from bot.backend import actor_headers, fetch_image, BackendError
from bot.rendering import send_text
from bot.copilot_flow import seen
from aiogram.exceptions import TelegramAPIError

router = Router()


async def clear_flow(state):
    # Preserve the shared recent-update ledger when a legacy flow completes.
    events = (await state.get_data()).get("copilot_seen", [])
    await state.clear()
    await state.update_data(copilot_seen=events)


def valid_task_response(data):
    if not isinstance(data, dict):
        return False
    if data.get("status") == "done":
        return isinstance(data.get("result"), dict)
    if data.get("status") != "need_info" or not isinstance(data.get("session_id"), str) or not data["session_id"]:
        return False
    questions = data.get("questions")
    return isinstance(questions, list) and bool(questions) and all(
        isinstance(question, dict) and isinstance(question.get("key"), str)
        and bool(question["key"]) and isinstance(question.get("question"), str)
        and bool(question["question"].strip()) for question in questions)


class AgentStates(StatesGroup):
    waiting_task_description = State()
    asking_details = State()
    running_agent = State()


class ImageStates(StatesGroup):
    waiting_platform = State()
    waiting_use_case = State()
    waiting_message = State()
    waiting_variants = State()
    waiting_overlay = State()
    running_image = State()


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


async def independent_request_allowed(callback):
    from bot.project_navigation import binding
    try:
        current = await binding(callback.from_user.id, callback.message.chat.id)
    except (BackendError, ValueError, KeyError, TypeError):
        await callback.answer("Не удалось проверить текущий проект. Откройте меню.", show_alert=True)
        return False
    if current["active"] is not None:
        await callback.answer("Для отдельной задачи нажмите «Новый запрос» в главном меню.", show_alert=True)
        return False
    return True

@router.callback_query(F.data.in_(AGENT_CONFIG.keys()))
async def choose_agent(callback: CallbackQuery, state: FSMContext):
    from .history import private_callback
    if not await private_callback(callback):
        return
    if not await independent_request_allowed(callback):
        return
    agent_key = callback.data
    cfg = AGENT_CONFIG[agent_key]

    await state.update_data(
        agent_key=agent_key,
        agent_type=cfg["agent_type"],
        answers={},
        task_description=None,
        session_id=None,
        current_question=None,
        use_fallback=False,
    )
    await state.set_state(AgentStates.waiting_task_description)

    await callback.message.edit_text(
        f"Окей, работаем с агентом: <b>{cfg['name']}</b>.\n\n"
        "Опиши, пожалуйста, свою задачу в свободной форме.\n\n"
        "Например: «Нужна стратегия для студии массажа» "
        "или «Сделай контент-план для ТГ-канала про IT»."
    )
    await callback.answer()


@router.callback_query(F.data == "generate_image")
async def choose_image(callback: CallbackQuery, state: FSMContext):
    from .history import private_callback
    if not await private_callback(callback):
        return
    if not await independent_request_allowed(callback):
        return
    await state.update_data(image_payload={})
    await state.set_state(ImageStates.waiting_platform)
    await callback.message.edit_text(
        "Для какой платформы нужна картинка? (instagram/telegram/vk/web/auto)"
    )
    await callback.answer()


@router.message(ImageStates.waiting_platform, F.text & ~F.text.startswith("/"))
async def image_platform(message: types.Message, state: FSMContext):
    if await seen(state, f"m:{message.message_id}"):
        return
    data = await state.get_data()
    payload = data.get("image_payload", {})
    payload["platform"] = message.text.strip().lower()
    await state.update_data(image_payload=payload)
    await state.set_state(ImageStates.waiting_use_case)
    await message.answer("Какой формат? (post/story/banner/hero/block/auto)")


@router.message(ImageStates.waiting_use_case, F.text & ~F.text.startswith("/"))
async def image_use_case(message: types.Message, state: FSMContext):
    if await seen(state, f"m:{message.message_id}"):
        return
    data = await state.get_data()
    payload = data.get("image_payload", {})
    payload["use_case"] = message.text.strip().lower()
    await state.update_data(image_payload=payload)
    await state.set_state(ImageStates.waiting_message)
    await message.answer("Опиши, что должно быть на изображении.")


@router.message(ImageStates.waiting_message, F.text & ~F.text.startswith("/"))
async def image_message(message: types.Message, state: FSMContext):
    if await seen(state, f"m:{message.message_id}"):
        return
    data = await state.get_data()
    payload = data.get("image_payload", {})
    payload["message"] = message.text.strip()
    await state.update_data(image_payload=payload)
    await state.set_state(ImageStates.waiting_variants)
    await message.answer("Сколько вариантов нужно? (1-3)")


@router.message(ImageStates.waiting_variants, F.text & ~F.text.startswith("/"))
async def image_variants(message: types.Message, state: FSMContext):
    if await seen(state, f"m:{message.message_id}"):
        return
    data = await state.get_data()
    payload = data.get("image_payload", {})
    try:
        variants = int(message.text.strip())
    except ValueError:
        variants = 1
    payload["variants"] = max(1, min(variants, 3))
    await state.update_data(image_payload=payload)
    await state.set_state(ImageStates.waiting_overlay)
    await message.answer(
        "Нужен ли текст на картинке? Если да, пришли так: "
        "Заголовок | Подзаголовок | CTA. Или напиши «-»."
    )


def parse_overlay(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned in {"-", "нет", "no", "без текста"}:
        return None
    parts = [p.strip() for p in cleaned.split("|")]
    overlay = {}
    if parts:
        overlay["headline"] = parts[0]
    if len(parts) > 1:
        overlay["subtitle"] = parts[1]
    if len(parts) > 2:
        overlay["cta"] = parts[2]
    return overlay


@router.message(ImageStates.waiting_overlay, F.text & ~F.text.startswith("/"))
async def image_overlay(message: types.Message, state: FSMContext):
    if await seen(state, f"m:{message.message_id}"):
        return
    data = await state.get_data()
    payload = data.get("image_payload", {})
    overlay = parse_overlay(message.text)
    if overlay:
        payload["overlay"] = overlay
    await state.update_data(image_payload=payload)
    await state.set_state(ImageStates.running_image)
    await message.answer("Генерирую изображение 🤖...")

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{settings.API_BASE_URL}/images/generate", json=payload,
                                     headers=actor_headers(message.from_user.id))
            resp.raise_for_status()
            resp_data = resp.json()
        if not isinstance(resp_data, dict) or not isinstance(resp_data.get("images"), list) or not resp_data["images"]:
            raise ValueError()
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            for image in resp_data["images"]:
                try:
                    if not isinstance(image, dict) or not isinstance(image.get("url"), str):
                        raise BackendError("Invalid image")
                    content = await fetch_image(client, image["url"], message.from_user.id)
                    await message.answer_photo(types.BufferedInputFile(content, filename="image.png"))
                except (BackendError, httpx.HTTPError, TelegramAPIError):
                    await message.answer("Изображение создано, но доставить его не удалось. Повторная генерация не запускается автоматически.")
    except (httpx.HTTPError, ValueError, TypeError):
        await message.answer("Не удалось подтвердить генерацию изображения. Запрос мог быть обработан; повторный запуск создаёт новую генерацию.")
    finally:
        await clear_flow(state)



@router.message(AgentStates.waiting_task_description, F.text & ~F.text.startswith("/"))
async def get_task_description(message: types.Message, state: FSMContext):
    if await seen(state, f"m:{message.message_id}"):
        return
    await state.update_data(task_description=message.text)
    data = await state.get_data()
    agent_key = data["agent_key"]
    agent_type = data["agent_type"]

    payload = {
        "user": {
            "telegram_id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
        },
        "agent_type": agent_type,
        "task_description": message.text,
        "answers": {},
        "mode": "text",
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.API_BASE_URL}/tasks/start",
                json=payload,
            headers=actor_headers(message.from_user.id),
            )
        if resp.status_code >= 400:
            raise RuntimeError("Backend error")
        resp_data = resp.json()
        if not valid_task_response(resp_data):
            raise ValueError()
    except (httpx.HTTPError, ValueError, TypeError, RuntimeError):
        # Never fall back to another execution route after ambiguous acceptance.
        await clear_flow(state)
        await message.answer("Не удалось подтвердить запуск задачи. Она могла сохраниться: проверьте /history перед новым запуском.")
        return

    if resp_data.get("status") == "need_info":
        questions = resp_data.get("questions") or []
        if not questions:
            await message.answer("Нужно чуть больше деталей. Давай уточним задачу.")
            return
        current = questions[0]
        await state.update_data(
            session_id=resp_data.get("session_id"),
            current_question=current,
        )
        await state.set_state(AgentStates.asking_details)
        await message.answer(current["question"])
        return

    if resp_data.get("status") == "done":
        await clear_flow(state)
        await send_orchestrator_result(message, resp_data.get("result", {}))
        return

    await message.answer("Неожиданный ответ от сервера. Попробуй ещё раз.")


@router.message(AgentStates.asking_details, F.text & ~F.text.startswith("/"))
async def ask_details(message: types.Message, state: FSMContext):
    if await seen(state, f"m:{message.message_id}"):
        return
    data = await state.get_data()
    if data.get("use_fallback"):
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
        return

    session_id = data.get("session_id")
    current_question = data.get("current_question")
    if not session_id or not current_question:
        await message.answer("Сессия устарела. Начни задачу заново.")
        await clear_flow(state)
        return

    key = current_question["key"]
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{settings.API_BASE_URL}/tasks/answer",
                json={"session_id": session_id, "key": key, "value": message.text},
                headers=actor_headers(message.from_user.id))
            resp.raise_for_status()
            resp_data = resp.json()
        if not valid_task_response(resp_data):
            raise ValueError()
    except (httpx.HTTPError, ValueError, TypeError):
        await message.answer("Не удалось получить ответ. Можно повторить ответ на тот же вопрос; новый запуск не создаётся.")
        return
    if resp_data.get("status") == "need_info":
        questions = resp_data.get("questions") or []
        current = questions[0] if questions else None
        if not current:
            await message.answer("Нужны ещё уточнения, но вопросов не пришло.")
            return
        await state.update_data(current_question=current)
        await message.answer(current["question"])
        return

    if resp_data.get("status") == "done":
        await clear_flow(state)
        await send_orchestrator_result(message, resp_data.get("result", {}))
        return

    await message.answer("Неожиданный ответ от сервера. Попробуй ещё раз.")


# ===========================
# Форматирование ответов агентов
# ===========================

async def send_orchestrator_result(message: types.Message, result: dict) -> None:
    content = result.get("content") if isinstance(result, dict) else None
    if not isinstance(content, str) or not content.strip():
        await send_text(message, "Не удалось прочитать результат задачи. Проверьте /history.")
        return
    await send_text(message, content)


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
        messages.append("\n".join(lines))

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
        messages.append("\n".join(lines))

    diagnosis = result.get("diagnosis") or []
    if diagnosis:
        lines = ["<b>Что может быть не так:</b>"]
        for d in diagnosis:
            lines.append(f"• {d}")
        messages.append("\n".join(lines))

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
        messages.append("\n".join(lines))

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
        messages.append("\n".join(lines))

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
        messages.append("\n".join(lines))

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
        messages.append("\n".join(lines))
    else:
        messages.append("Пока нет явных идей для экспериментов — попробуй уточнить нишу или формат.")

    return messages


def format_trends_details(result: dict) -> list[str]:
    messages: list[str] = []

    fmt_trends = result.get("format_trends") or []
    if fmt_trends:
        lines = ["<b>Форматные тренды:</b>"]
        for t in fmt_trends:
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
        messages.append("\n".join(lines))

    content_trends = result.get("content_trends") or []
    if content_trends:
        lines = ["<b>Сюжетные тренды:</b>"]
        for ct in content_trends:
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
        messages.append("\n".join(lines))

    mechanics = result.get("engagement_mechanics") or []
    if mechanics:
        lines = ["<b>Механики вовлечения:</b>"]
        for m in mechanics:
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
        messages.append("\n".join(lines))

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
            headers=actor_headers(message.from_user.id),
        )
        if resp.status_code >= 400:
            await clear_flow(state)
            await message.answer(
                "Произошла ошибка при выполнении задачи. Попробуй ещё раз позже."
            )
            return
        data_resp = resp.json()

    await clear_flow(state)

    task_id = data_resp["task_id"]
    result = data_resp["result"]

    # Для каждого агента — свой дайджест + кнопка "подробнее"
    if agent_key == "agent_strategy":
        text = format_strategy_result(result)
        await send_text(message, text, reply_markup=kb_strategy_more(task_id))

    elif agent_key == "agent_content":
        msgs = format_content_result_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await send_text(message, txt, reply_markup=kb_content_more(task_id))
            else:
                await send_text(message, txt)

    elif agent_key == "agent_analytics":
        msgs = format_analytics_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await send_text(message, txt, reply_markup=kb_analytics_more(task_id))
            else:
                await send_text(message, txt)

    elif agent_key == "agent_promo":
        msgs = format_promo_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await send_text(message, txt, reply_markup=kb_promo_more(task_id))
            else:
                await send_text(message, txt)

    elif agent_key == "agent_trends":
        msgs = format_trends_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await send_text(message, txt, reply_markup=kb_trends_more(task_id))
            else:
                await send_text(message, txt)


# ===========================
# Callback’и “Показать подробнее”
# ===========================

def saved_output(formatter, result):
    """Fail closed on historical or malformed nested provider payloads."""
    try:
        output = formatter(result)
        parts = [output] if isinstance(output, str) else output
        if not isinstance(parts, list) or not all(isinstance(text, str) for text in parts):
            return None
        return output
    except (AttributeError, TypeError, ValueError, KeyError, IndexError):
        return None


async def fetch_task_result(task_id: int, actor_id: int) -> dict | None:
    from .history import fetch_task
    task = await fetch_task(task_id, actor_id)
    return task.get("result") if task and task.get("status") == "done" else None


@router.callback_query(F.data.startswith("strategy_full:"))
async def on_strategy_full(callback: CallbackQuery):
    from .history import private_callback, task_id_from_callback
    if not await private_callback(callback):
        return
    task_id = task_id_from_callback(callback.data)
    if task_id is None:
        await callback.answer("Некорректное действие. Откройте /history", show_alert=True)
        return
    result = await fetch_task_result(task_id, callback.from_user.id)
    if not result:
        await callback.answer("Не удалось получить стратегию 😔", show_alert=True)
        return
    text = saved_output(format_strategy_full, result)
    if text is None:
        await callback.answer("Не удалось прочитать сохранённый результат.", show_alert=True)
        return
    await send_text(callback.message, text)
    await callback.answer()


@router.callback_query(F.data.startswith("content_more:"))
async def on_content_more(callback: CallbackQuery):
    from .history import private_callback, task_id_from_callback
    if not await private_callback(callback):
        return
    task_id = task_id_from_callback(callback.data)
    if task_id is None:
        await callback.answer("Некорректное действие. Откройте /history", show_alert=True)
        return
    result = await fetch_task_result(task_id, callback.from_user.id)
    if not result:
        await callback.answer("Не удалось получить контент 😔", show_alert=True)
        return
    msgs = saved_output(format_content_more_posts, result)
    if msgs is None:
        await callback.answer("Не удалось прочитать сохранённый результат.", show_alert=True)
        return
    for txt in msgs:
        await send_text(callback.message, txt)
    await callback.answer()


@router.callback_query(F.data.startswith("analytics_more:"))
async def on_analytics_more(callback: CallbackQuery):
    from .history import private_callback, task_id_from_callback
    if not await private_callback(callback):
        return
    task_id = task_id_from_callback(callback.data)
    if task_id is None:
        await callback.answer("Некорректное действие. Откройте /history", show_alert=True)
        return
    result = await fetch_task_result(task_id, callback.from_user.id)
    if not result:
        await callback.answer("Не удалось получить аналитику 😔", show_alert=True)
        return
    msgs = saved_output(format_analytics_details, result)
    if msgs is None:
        await callback.answer("Не удалось прочитать сохранённый результат.", show_alert=True)
        return
    for txt in msgs:
        await send_text(callback.message, txt)
    await callback.answer()


@router.callback_query(F.data.startswith("promo_more:"))
async def on_promo_more(callback: CallbackQuery):
    from .history import private_callback, task_id_from_callback
    if not await private_callback(callback):
        return
    task_id = task_id_from_callback(callback.data)
    if task_id is None:
        await callback.answer("Некорректное действие. Откройте /history", show_alert=True)
        return
    result = await fetch_task_result(task_id, callback.from_user.id)
    if not result:
        await callback.answer("Не удалось получить данные по рекламе 😔", show_alert=True)
        return
    msgs = saved_output(format_promo_details, result)
    if msgs is None:
        await callback.answer("Не удалось прочитать сохранённый результат.", show_alert=True)
        return
    for txt in msgs:
        await send_text(callback.message, txt)
    await callback.answer()


@router.callback_query(F.data.startswith("trends_more:"))
async def on_trends_more(callback: CallbackQuery):
    from .history import private_callback, task_id_from_callback
    if not await private_callback(callback):
        return
    task_id = task_id_from_callback(callback.data)
    if task_id is None:
        await callback.answer("Некорректное действие. Откройте /history", show_alert=True)
        return
    result = await fetch_task_result(task_id, callback.from_user.id)
    if not result:
        await callback.answer("Не удалось получить тренды 😔", show_alert=True)
        return
    msgs = saved_output(format_trends_details, result)
    if msgs is None:
        await callback.answer("Не удалось прочитать сохранённый результат.", show_alert=True)
        return
    for txt in msgs:
        await send_text(callback.message, txt)
    await callback.answer()


@router.message(AgentStates.waiting_task_description, ~F.text)
@router.message(AgentStates.asking_details, ~F.text)
@router.message(ImageStates.waiting_platform, ~F.text)
@router.message(ImageStates.waiting_use_case, ~F.text)
@router.message(ImageStates.waiting_message, ~F.text)
@router.message(ImageStates.waiting_variants, ~F.text)
@router.message(ImageStates.waiting_overlay, ~F.text)
async def unsupported_flow_input(message: types.Message):
    await message.answer("Пришлите ответ текстом или используйте /cancel.")
