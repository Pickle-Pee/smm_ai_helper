"""Telegram navigation for durable, owner-scoped project sessions.

Only presentation and transport live here. PostgreSQL owns selection, capability
checks, concurrency and dialogue identity; FSM is used for unsubmitted forms.
"""
import base64
import re
from datetime import datetime
from urllib.parse import urlencode

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pydantic import ValidationError

from bot import backend
from bot.rendering import send_text

router = Router(name="project_navigation")
context_router = Router(name="durable_project_context")
NEW = "➕ Новый запрос"
HISTORY = "📂 Проекты и история"
CONTEXT = "🧠 Текущий контекст"
PROFILE = "🏢 Профиль бизнеса"
HELP = "⚙️ Настройки / Помощь"
BACK = "⬅️ Главное меню"
MENU_TEXTS = {NEW, HISTORY, CONTEXT, PROFILE, HELP, BACK, "🕘 История запросов", "📂 Мои проекты"}
SOURCES = {"all": "Все типы", "graph": "Стратегии", "workflow": "Анализы", "task": "Задачи",
           "receipt": "Другие запросы", "conversation": "Диалоги", "legacy": "Старый чат"}
STATUSES = {"all": "Все статусы", "completed": "Завершённые", "running": "В работе", "failed": "Ошибки"}
STATUS_LABELS = {"completed": "Завершено", "completed_with_limitations": "Готово с ограничениями",
    "done": "Завершено", "succeeded": "Завершено", "running": "В работе", "queued": "В очереди",
    "created": "Создано", "failed": "Не завершено", "error": "Ошибка", "blocked": "Нужны данные",
    "needs_input": "Нужны данные", "awaiting_creative": "Анализ готов", "awaiting_mentor": "Креатив готов",
    "saved": "Сохранено", "available": "Доступно", "legacy": "Архив"}


class NavigationStates(StatesGroup):
    search = State()
    profile_product = State()
    profile_audience = State()
    profile_goal = State()


def main_keyboard():
    return types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text=NEW), types.KeyboardButton(text=HISTORY)],
        [types.KeyboardButton(text=CONTEXT)],
        [types.KeyboardButton(text=PROFILE), types.KeyboardButton(text=HELP)],
    ], resize_keyboard=True, is_persistent=True, input_field_placeholder="Выберите проект или напишите запрос")


def inline(buttons):
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=title[:60], callback_data=data)] for title, data in buttons])


async def private(event):
    message = event.message if isinstance(event, types.CallbackQuery) or hasattr(event, "data") else event
    valid = (message is not None and message.chat.type == "private"
             and message.chat.id == event.from_user.id)
    if not valid:
        if hasattr(event, "data"):
            await event.answer("Откройте личный чат с ботом.")
        else:
            await event.answer("Откройте личный чат с ботом.")
    return valid


def pack(public_id):
    """Canonical compact source identity; never put request text in callbacks."""
    if not isinstance(public_id, str) or ":" not in public_id:
        raise ValueError("Invalid project")
    kind, value = public_id.split(":", 1)
    if kind in {"g", "r"} and re.fullmatch(r"[0-9a-f]{64}", value):
        return kind + base64.urlsafe_b64encode(bytes.fromhex(value)).decode().rstrip("=")
    if kind == "w" and re.fullmatch(r"[0-9a-f]{32}", value):
        return kind + base64.urlsafe_b64encode(bytes.fromhex(value)).decode().rstrip("=")
    if kind in {"t", "c"} and re.fullmatch(r"[1-9][0-9]{0,18}" if kind == "t" else r"0|[1-9][0-9]{0,18}", value):
        return kind + value
    if public_id == "l:chat":
        return "lchat"
    raise ValueError("Invalid project")


def unpack(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid project")
    kind, encoded = value[0], value[1:]
    if kind in {"g", "r", "w"}:
        size = 22 if kind == "w" else 43
        if not re.fullmatch(r"[A-Za-z0-9_-]{" + str(size) + r"}", encoded):
            raise ValueError("Invalid project")
        public_id = kind + ":" + base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).hex()
    elif kind in {"t", "c"}:
        public_id = kind + ":" + encoded
    elif value == "lchat":
        public_id = "l:chat"
    else:
        raise ValueError("Invalid project")
    if pack(public_id) != value:
        raise ValueError("Invalid project")
    return public_id


def callback(action, public_id, version=None):
    suffix = ""
    if version is not None:
        if type(version) is not int or not 0 <= version < 2**63: raise ValueError("Invalid version")
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        encoded = "0" if version == 0 else ""
        while version:
            version, remainder = divmod(version, 36)
            encoded = digits[remainder] + encoded
        suffix = ":" + encoded
    data = f"pn:{action}:{pack(public_id)}" + suffix
    if len(data.encode()) > 64:
        raise ValueError("Callback too long")
    return data


def date_label(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M") + " UTC"
    except (ValueError, AttributeError, TypeError):
        return "Дата не сохранена"


def status_label(value):
    return STATUS_LABELS.get(str(value).lower(), "Сохранённый запрос")


def metadata(item):
    value = item.get("metadata", item)
    if not isinstance(value, dict) or not isinstance(value.get("title"), str):
        raise ValueError("Invalid project metadata")
    pack(value["public_id"])
    return value


async def binding(actor, chat_id):
    data = await backend.request("GET", "/projects/context?" + urlencode({"chat_id": chat_id}), actor)
    if (not isinstance(data, dict) or "active" not in data or type(data.get("version")) is not int
            or not 0 <= data["version"] < 2**63):
        raise ValueError("Invalid binding")
    if data.get("active") is not None:
        metadata(data["active"])
    return data


def clear_old_actions(actor):
    from bot.handlers.chat import ACTION_STORE, ACTION_EXPIRES
    ACTION_STORE.pop(str(actor), None)
    ACTION_EXPIRES.pop(str(actor), None)


async def show_menu(message):
    await message.answer("SMM AI Helper\nВыберите сохранённый проект или начните новый запрос.",
                         reply_markup=main_keyboard(), parse_mode=None)


async def new_request(message, state):
    current = await binding(message.from_user.id, message.chat.id)
    confirmed = await backend.request("POST", "/projects/context", message.from_user.id, payload={
        "chat_id": message.chat.id, "expected_version": current["version"], "public_id": None})
    if (not isinstance(confirmed, dict) or "active" not in confirmed or confirmed["active"] is not None
            or type(confirmed.get("version")) is not int or confirmed["version"] != current["version"] + 1):
        raise ValueError("Invalid binding")
    await state.clear()
    clear_old_actions(message.from_user.id)
    await message.answer("Напишите новый запрос одним сообщением. Предыдущие проекты сохранены в истории.",
                         reply_markup=main_keyboard(), parse_mode=None)


async def show_history(message, actor, *, offset=0, source="all", status="all", query=None):
    params = {"limit": 8, "offset": offset}
    if source != "all": params["source_type"] = source
    if status != "all": params["status"] = status
    if query: params["query"] = query
    data = await backend.request("GET", "/projects/history?" + urlencode(params), actor)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or len(data["items"]) > 8:
        raise ValueError("Invalid history")
    items = [metadata(item) for item in data["items"]]
    buttons = [(f"{item['title'][:42]} · {status_label(item.get('status'))}", callback("c", item["public_id"]))
               for item in items]
    text = "Проекты и история\n" + ("\n".join(
        f"{i}. {item['title'][:100]}\n{date_label(item.get('last_activity_at'))} · {status_label(item.get('status'))}"
        for i, item in enumerate(items, 1)) or "Сохранённых запросов пока нет.")
    if query: text += "\n\nПоиск по началу названия. Показаны первые 8 совпадений; уточните название для поиска других записей."
    next_offset = data.get("next_offset")
    if type(next_offset) is int and 0 <= next_offset <= 10000:
        # Search is a bounded one-page preview; next pages require a fresh query.
        if not query: buttons.append(("Далее →", f"pn:p:{next_offset}:{source}:{status}"))
    if offset: buttons.append(("← Назад", f"pn:p:{max(0, offset - 8)}:{source}:{status}"))
    buttons += [("Фильтр по типу", "pn:types"), ("Фильтр по статусу", f"pn:statuses:{source}"),
                ("Поиск по названию", "pn:search"), ("Главное меню", "pn:home")]
    await send_text(message, text, reply_markup=inline(buttons))


async def show_card(message, actor, public_id):
    item = await backend.request("GET", f"/projects/items/{public_id}", actor)
    meta = metadata(item)
    if meta["public_id"] != public_id:
        raise ValueError("Wrong project")
    current = await binding(actor, message.chat.id)
    capabilities = item.get("capabilities", meta.get("capabilities", []))
    if not isinstance(capabilities, list): raise ValueError("Invalid capabilities")
    text = (f"{meta['title']}\n\nСоздан: {date_label(meta.get('created_at'))}\n"
            f"Статус: {status_label(meta.get('status'))}\nПоследняя активность: {date_label(meta.get('last_activity_at'))}")
    for key, label in (("goal", "Цель"), ("context_description", "Контекст")):
        if isinstance(item.get(key), str) and item[key]: text += f"\n\n{label}: {item[key][:800]}"
    artifacts = item.get("artifacts", [])
    if isinstance(artifacts, list) and all(isinstance(v, str) for v in artifacts):
        text += "\n\nРезультаты: " + (", ".join(artifacts)[:500] or "Пока недоступны")
    buttons = []
    for capability, title, action in (("resume_conversation", "Продолжить работу", "a"),
            ("view_result", "Посмотреть результат", "v"), ("view_history", "История обсуждения", "d"),
            ("view_feedback", "Обратная связь", "f"), ("start_new_from_source", "Новый запрос на основе этого", "n")):
        if capability in capabilities:
            buttons.append((title, callback(action, public_id, current["version"] if action in {"a", "n"} else None)))
    if "resume_conversation" not in capabilities:
        text += "\n\nПолное восстановление контекста для этой записи недоступно."
    buttons += [("Назад к истории", "pn:p:0:all:all"), ("Главное меню", "pn:home")]
    await send_text(message, text, reply_markup=inline(buttons))


async def show_result(message, actor, public_id, *, offset=0):
    item = await backend.request("GET", f"/projects/items/{public_id}", actor)
    meta = metadata(item)
    if meta["public_id"] != public_id: raise ValueError("Wrong project")
    result = item.get("result")
    if offset and meta["source_type"] != "legacy": raise ValueError("Invalid archive page")
    if not result:
        await send_text(message, "Сохранённый результат пока недоступен. Откройте карточку, чтобы проверить статус.")
    elif meta["source_type"] == "graph":
        from bot import copilot_contracts as dto, copilot_rendering as render
        saved = dto.RunResponse.model_validate(result)
        if saved.run_id != meta["source_id"]: raise ValueError("Wrong graph")
        for section in render.run(saved): await send_text(message, section)
    elif meta["source_type"] == "task":
        from bot.handlers.history import show_task
        await show_task(message, {"id": int(meta["source_id"]), "agent_type": item.get("agent_type"),
            "status": meta.get("status"), "result": result})
    elif meta["source_type"] == "workflow":
        from app.workflows.presentation import render_artifact
        from bot.workflow_contracts import Artifact
        artifacts = result.get("artifacts", result)
        if not isinstance(artifacts, dict): raise ValueError("Invalid artifacts")
        for value in artifacts.values():
            artifact = Artifact.model_validate(value).model_dump(mode="json")
            await send_text(message, render_artifact(artifact))
    elif meta["source_type"] == "receipt":
        from pydantic import TypeAdapter
        from bot import copilot_contracts as dto, copilot_rendering as render
        saved = TypeAdapter(dto.ExecuteResponse).validate_python(result)
        if isinstance(saved, dto.DirectResponse):
            for section in render.calculation(saved.calculation): await send_text(message, section)
        elif isinstance(saved, dto.ModuleResponse):
            for section in render.module(saved.result): await send_text(message, section)
        else: await send_text(message, "Для этого запроса нет отдельного завершённого результата.")
    elif meta["source_type"] == "legacy":
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list): raise ValueError("Invalid archive")
        messages = result["messages"]
        if len(messages) > 50: raise ValueError("Invalid archive window")
        # Page backwards through the saved global archive without claiming it
        # belongs to a project session or consulting project discussion state.
        newest = list(reversed(messages))
        page = list(reversed(newest[offset:offset + 8]))
        lines = []
        for saved in page:
            if not isinstance(saved, dict) or not isinstance(saved.get("role"), str) or not isinstance(saved.get("text"), str):
                raise ValueError("Invalid archive message")
            label = {"user": "Вы", "assistant": "Помощник"}.get(saved["role"], "Сохранённое сообщение")
            lines.append(label + ": " + saved["text"])
        text = "Архив общего чата\nЭти сообщения не разделены по проектам.\n\n" + ("\n\n".join(lines) or "Сообщений на этой странице нет.")
        if result.get("older_messages_omitted"):
            text += "\n\nАрхивное окно ограничено последними 50 сообщениями; более ранние сообщения здесь не показаны."
        buttons = []
        if offset + 8 < len(messages): buttons.append(("Более ранние сообщения →", callback("v", public_id) + ":" + str(offset + 8)))
        if offset: buttons.append(("← К новым сообщениям", callback("v", public_id) + ":" + str(max(0, offset - 8))))
        buttons += [("К карточке", callback("c", public_id)), ("Главное меню", "pn:home")]
        await send_text(message, text, reply_markup=inline(buttons))
        return
    else:
        await show_discussion(message, actor, public_id)
    await send_text(message, "Сохранённый результат.", reply_markup=inline([("К карточке", callback("c", public_id)), ("Главное меню", "pn:home")]))


async def show_discussion(message, actor, public_id, *, offset=0):
    data = await backend.request("GET", f"/projects/items/{public_id}/discussion?limit=10&offset={offset}", actor)
    if not isinstance(data, dict) or data.get("public_id") != public_id or not isinstance(data.get("turns"), list):
        raise ValueError("Invalid discussion")
    lines = []
    for turn in data["turns"][:10]:
        if not isinstance(turn.get("question"), str) or not isinstance(turn.get("reply"), str):
            raise ValueError("Invalid turn")
        lines.append("Вы: " + turn["question"][:1200] + "\nПомощник: " + turn["reply"][:2000])
    buttons = []
    next_offset = data.get("next_offset")
    if type(next_offset) is int and 0 <= next_offset <= 10000:
        buttons.append(("Далее →", callback("d", public_id) + ":" + str(next_offset)))
    if offset: buttons.append(("← Назад", callback("d", public_id) + ":" + str(max(0, offset - 10))))
    buttons += [("К карточке", callback("c", public_id)), ("Главное меню", "pn:home")]
    await send_text(message, "История обсуждения\n\n" + ("\n\n".join(lines) or "В этом проекте пока нет сообщений."), reply_markup=inline(buttons))


async def show_profile(message, actor):
    buttons = [("Заполнить / изменить профиль", "pn:profile"), ("Главное меню", "pn:home")]
    introduction = "Профиль бизнеса используется как исходные сведения для новых запросов. Сохранённые проекты имеют собственный контекст."
    try:
        data = await backend.request("GET", f"/brand-profile/{actor}", actor)
    except backend.BackendError:
        await send_text(message, introduction + "\n\nСохранённый профиль не найден или временно недоступен.", reply_markup=inline(buttons))
        return
    if not isinstance(data, dict): raise ValueError("Invalid profile")
    lines = []
    for key, label in (("brand_name", "Название"), ("product_description", "Продукт"), ("audience", "Аудитория"),
                       ("goals", "Цели"), ("channels", "Каналы"), ("tone", "Тон общения")):
        value = data.get(key)
        if value is None: continue
        if isinstance(value, list) and all(isinstance(v, str) for v in value): value = ", ".join(value)
        if not isinstance(value, str): raise ValueError("Invalid profile field")
        if value: lines.append(f"{label}: {value[:2000]}" + ("… (поле сокращено)" if len(value) > 2000 else ""))
    await send_text(message, introduction + "\n\n" + ("\n\n".join(lines) or "Сведения ещё не заполнены."), reply_markup=inline(buttons))


@router.message(CommandStart())
@router.message(Command("menu"))
async def start(message: types.Message):
    if await private(message): await show_menu(message)


@router.message(Command("new", "history", "projects", "active", "help"))
@router.message(F.text.in_(MENU_TEXTS))
async def navigate(message: types.Message, state: FSMContext):
    if not await private(message): return
    text = message.text.split("@")[0].split()[0] if message.text.startswith("/") else message.text
    try:
        if text in {NEW, "/new"}: await new_request(message, state)
        elif text in {HISTORY, "🕘 История запросов", "📂 Мои проекты", "/history", "/projects"}:
            await show_history(message, message.from_user.id)
        elif text in {CONTEXT, "/active"}:
            current = await binding(message.from_user.id, message.chat.id)
            active = current.get("active")
            await send_text(message, "Текущий проект: " + active["title"] if active else "Активный проект не выбран. Откройте историю и нажмите «Продолжить работу».",
                reply_markup=inline([("Карточка проекта", callback("c", active["public_id"]))]) if active else main_keyboard())
        elif text == PROFILE:
            await show_profile(message, message.from_user.id)
        elif text in {HELP, "/help"}:
            await send_text(message, "В истории выберите проект и нажмите «Продолжить работу». Обычный текст продолжит этот проект, даже после перезапуска.\n\n"
                "«Новый запрос» завершает выбор проекта и сохраняет историю. /cancel отменяет только неподтверждённые уточнения.\n"
                "Команды: /copilot_runs, /case_history, /history, /runs, /brand.\nЧасовой пояс дат в истории: UTC.", reply_markup=main_keyboard())
        else:
            # Leaving an unsubmitted form does not deactivate a saved project.
            if await state.get_state() in {s.state for s in NavigationStates.__all_states__}: await state.clear()
            await show_menu(message)
    except (backend.BackendError, ValueError, KeyError, TypeError):
        await send_text(message, "Не удалось подтвердить состояние проекта. Обновите историю или текущий контекст. Генерация автоматически не запускается.", reply_markup=main_keyboard())


@router.callback_query(F.data.startswith("pn:"))
async def navigation_callback(event: types.CallbackQuery, state: FSMContext):
    if not await private(event): return
    await event.answer()
    try:
        data = event.data
        if not isinstance(data, str) or len(data.encode()) > 64: raise ValueError("Invalid callback")
        parts = data.split(":")
        if data == "pn:home":
            if await state.get_state() in {s.state for s in NavigationStates.__all_states__}: await state.clear()
            await show_menu(event.message)
        elif data == "pn:types":
            await send_text(event.message, "Тип сохранённого запроса", reply_markup=inline([
                (title, f"pn:p:0:{source}:all") for source, title in SOURCES.items()]))
        elif len(parts) == 3 and parts[1] == "statuses" and parts[2] in SOURCES:
            await send_text(event.message, "Статус запроса", reply_markup=inline([
                (title, f"pn:p:0:{parts[2]}:{status}") for status, title in STATUSES.items()]))
        elif data == "pn:search":
            await state.set_state(NavigationStates.search)
            await send_text(event.message, "Введите начало названия (до 100 символов). Будут показаны первые 8 совпадений. Вернуться: «Главное меню».", reply_markup=inline([("Главное меню", "pn:home")]))
        elif data == "pn:profile":
            await state.set_state(NavigationStates.profile_product)
            await send_text(event.message, "Что за продукт или услугу вы предлагаете?", reply_markup=inline([("Главное меню", "pn:home")]))
        elif len(parts) == 5 and parts[1] == "p" and re.fullmatch(r"0|[1-9][0-9]{0,4}", parts[2]) and int(parts[2]) <= 10000 and parts[3] in SOURCES and parts[4] in STATUSES:
            await show_history(event.message, event.from_user.id, offset=int(parts[2]), source=parts[3], status=parts[4])
        elif len(parts) in {3, 4} and parts[1] in {"c", "v", "d", "f", "a", "n"}:
            public_id = unpack(parts[2])
            action = parts[1]
            if action in {"a", "n"}:
                if len(parts) != 4 or not re.fullmatch(r"[0-9a-z]{1,13}", parts[3]): raise ValueError("Invalid version")
                version = int(parts[3], 36)
                if version >= 2**63: raise ValueError("Invalid version")
                if action == "n":
                    item = await backend.request("GET", f"/projects/items/{public_id}", event.from_user.id)
                    meta = metadata(item)
                    if meta["public_id"] != public_id: raise ValueError("Wrong source")
                confirmed = await backend.request("POST", "/projects/context", event.from_user.id, payload={
                    "chat_id": event.message.chat.id, "expected_version": version,
                    "public_id": public_id if action == "a" else None})
                if (not isinstance(confirmed, dict) or "active" not in confirmed
                        or type(confirmed.get("version")) is not int or confirmed["version"] != version + 1):
                    raise ValueError("Invalid binding")
                if action == "n" and confirmed["active"] is not None: raise ValueError("Invalid reset")
                if action == "a" and metadata(confirmed["active"])["public_id"] != public_id:
                    raise ValueError("Wrong activation")
                await state.clear()
                clear_old_actions(event.from_user.id)
                if action == "n":
                    seed = "\n".join(value for value in [
                        "Источник: " + meta["title"],
                        "Сохранённая цель: " + item["goal"][:1000] if isinstance(item.get("goal"), str) and item["goal"] else "",
                        "Сохранённое описание: " + item["context_description"][:1500]
                            if isinstance(item.get("context_description"), str) and item["context_description"] else "",
                    ] if value)
                    await state.update_data(navigation_seed=seed)
                    await send_text(event.message, f"Новый запрос на основе «{meta['title']}».\nИсходный проект сохранён. В следующую задачу будут добавлены эти сведения как справочные данные, требующие проверки:\n\n{seed}\n\nОпишите новую задачу и исправьте неактуальные сведения.", reply_markup=main_keyboard())
                else:
                    active = metadata(confirmed["active"])
                    if active["public_id"] != public_id: raise ValueError("Wrong activation")
                    components = confirmed.get("restored_components", [])
                    if not isinstance(components, list) or not all(isinstance(v, str) for v in components): raise ValueError("Invalid components")
                    await send_text(event.message, f"Вы вернулись к проекту:\n{active['title']}\n\nЧто восстановлено:\n" +
                        "\n".join("• " + value for value in components) + "\n\nМожем продолжить работу. Напишите, что хотите изменить, уточнить или проверить.", reply_markup=main_keyboard())
            elif action == "d" and len(parts) == 4:
                if not re.fullmatch(r"0|[1-9][0-9]{0,4}", parts[3]) or int(parts[3]) > 10000: raise ValueError("Invalid offset")
                await show_discussion(event.message, event.from_user.id, public_id, offset=int(parts[3]))
            elif action == "v" and len(parts) == 4:
                if not re.fullmatch(r"0|[1-9][0-9]{0,2}", parts[3]) or int(parts[3]) >= 50: raise ValueError("Invalid archive offset")
                await show_result(event.message, event.from_user.id, public_id, offset=int(parts[3]))
            elif len(parts) != 3: raise ValueError("Invalid callback")
            elif action == "c": await show_card(event.message, event.from_user.id, public_id)
            elif action == "v": await show_result(event.message, event.from_user.id, public_id)
            elif action == "d": await show_discussion(event.message, event.from_user.id, public_id)
            elif action == "f":
                item = await backend.request("GET", f"/projects/items/{public_id}", event.from_user.id)
                reports = item.get("feedback", [])
                await send_text(event.message, "Обратная связь пользователя (не независимая проверка):\n" +
                    ("\n".join(str(value.get("notes", ""))[:1000] for value in reports[:5]) or "Обратная связь пока не сохранена."),
                    reply_markup=inline([("К карточке", callback("c", public_id))]))
        else: raise ValueError("Invalid callback")
    except (backend.BackendError, ValueError, KeyError, TypeError, ValidationError):
        await send_text(event.message, "Действие недоступно или устарело. Откройте историю заново. Состояние проекта не подтверждено; генерация автоматически не запускается.", reply_markup=main_keyboard())


@router.message(StateFilter(NavigationStates.search, NavigationStates.profile_product,
                            NavigationStates.profile_audience, NavigationStates.profile_goal), F.text, ~F.text.startswith("/"))
async def form_input(message: types.Message, state: FSMContext):
    if not await private(message): return
    value = message.text.strip()
    current = await state.get_state()
    if not value or len(value) > (100 if current == NavigationStates.search.state else 2000):
        await send_text(message, "Введите непустой текст короче " + ("100" if current == NavigationStates.search.state else "2000") + " символов.")
        return
    try:
        if current == NavigationStates.search.state:
            await show_history(message, message.from_user.id, query=value)
            await state.set_state(None)
        elif current == NavigationStates.profile_product.state:
            await state.update_data(navigation_profile={"product_description": value})
            await state.set_state(NavigationStates.profile_audience)
            await send_text(message, "Кто ваша целевая аудитория?")
        elif current == NavigationStates.profile_audience.state:
            data = (await state.get_data())["navigation_profile"]
            data["audience"] = value
            await state.update_data(navigation_profile=data)
            await state.set_state(NavigationStates.profile_goal)
            await send_text(message, "Какова цель продвижения?")
        else:
            data = (await state.get_data())["navigation_profile"]
            data["goals"] = [value]
            await backend.request("PUT", "/workflows/profile", message.from_user.id, payload=data)
            await state.clear()
            await send_text(message, "Профиль бизнеса сохранён. Выберите «Новый запрос», чтобы использовать его в новой работе.", reply_markup=main_keyboard())
    except (backend.BackendError, ValueError, KeyError, TypeError):
        await send_text(message, "Не удалось подтвердить действие. Попробуйте позже или вернитесь в главное меню.", reply_markup=main_keyboard())


@context_router.message(F.text, ~F.text.startswith("/"))
async def active_message(message: types.Message, state: FSMContext):
    if not await private(message): return
    try:
        current = await binding(message.from_user.id, message.chat.id)
        if current.get("active") is None: raise SkipHandler()
        data = await backend.request("POST", "/projects/context/messages", message.from_user.id, payload={
            "chat_id": message.chat.id, "expected_version": current["version"],
            "request_key": f"tg:{message.from_user.id}:{message.chat.id}:{message.message_id}", "text": message.text})
        if (not isinstance(data, dict) or not isinstance(data.get("reply"), str) or not data["reply"].strip()
                or data.get("public_id") != current["active"]["public_id"]): raise ValueError("Invalid reply")
        await send_text(message, data["reply"], reply_markup=main_keyboard())
    except (backend.BackendError, ValueError, TypeError, KeyError):
        await send_text(message, "Не удалось подтвердить ответ для текущего проекта. Проверьте историю обсуждения. При неизвестном исходе повторная генерация автоматически не запускается.", reply_markup=main_keyboard())
