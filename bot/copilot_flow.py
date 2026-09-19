"""Telegram continuation/presentation state. Backend owns execution and run status."""
import base64
import hashlib
import re

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pydantic import ValidationError

from bot import copilot_contracts as dto, copilot_rendering as render
from bot.copilot_client import CopilotClient, CopilotError, RUN_ID
from bot.rendering import send_text

client = CopilotClient()
URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


class CopilotStates(StatesGroup):
    pending = State()


def request_key(actor, chat, message):
    return f"tg:{actor}:{chat}:{message}"


def run_callback(run_id):
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run ID")
    return "cs:" + base64.urlsafe_b64encode(bytes.fromhex(run_id)).decode().rstrip("=")


def decode_run(value):
    if not re.fullmatch(r"cs:[A-Za-z0-9_-]{43}", value):
        raise ValueError("Invalid callback")
    run_id = base64.urlsafe_b64decode(value[3:] + "=").hex()
    if run_callback(run_id) != value:
        raise ValueError("Noncanonical callback")
    return run_id


def keyboard(buttons):
    kb = InlineKeyboardBuilder()
    for title, data in buttons:
        kb.button(text=title, callback_data=data)
    kb.adjust(1)
    return kb.as_markup()


def status_keyboard(run_id):
    return keyboard([("Проверить готовность", run_callback(run_id))])


def action(pending, name):
    return f"cp:{pending['token']}:{name}"


async def save(state, pending, *, renew=False):
    if renew:
        pending["revision"] += 1
    pending["token"] = hashlib.sha256(
        f"{pending['payload']['request_key']}:{pending['revision']}".encode()).hexdigest()[:16]
    await state.update_data(copilot_pending=pending)
    await state.set_state(CopilotStates.pending)


async def seen(state, event):
    data = await state.get_data()
    events = data.get("copilot_seen", [])
    if event in events:
        return True
    await state.update_data(copilot_seen=[*events[-63:], event])
    return False


def urls(message):
    values = URL.findall(message.text or "")
    values.extend(e.url for e in (getattr(message, "entities", None) or []) if e.type == "text_link" and e.url)
    return list(dict.fromkeys(u.rstrip(".,;!?)\"'") for u in values))


async def finish(state):
    await state.update_data(copilot_pending=None)
    await state.set_state(None)


async def prompt_urls(message, state, pending):
    pending["phase"] = "urls"
    await save(state, pending, renew=True)
    count = len(pending["payload"].get("competitor_urls", []))
    buttons = [("Мой сайт", action(pending, "own")), (f"Конкурент ({count}/3)", action(pending, "competitor")),
        ("Источник рынка", action(pending, "market")), ("Не использовать как источник", action(pending, "skip")),
        ("Отмена", action(pending, "cancel"))]
    await send_text(message, f"Как использовать ссылку? Конкуренты: {count}/3.\n{pending['urls'][0]}", reply_markup=keyboard(buttons))


async def prompt_fields(message, state, pending, *, grouped=False):
    pending["phase"] = "fields"
    await save(state, pending, renew=True)
    fields = pending["fields"]
    if grouped:
        text = "Чтобы продолжить, нужно уточнить:\n" + "\n".join(
            f"{i}. {render.FIELDS.get(key, 'Уточните задачу и необходимые исходные данные.')}" for i, key in enumerate(fields, 1))
        text += "\n\nОтветьте по порядку, по одному сообщению."
    else:
        text = render.FIELDS.get(fields[0], "Уточните задачу и необходимые исходные данные.")
    await send_text(message, text, reply_markup=keyboard([("Отмена", action(pending, "cancel"))]))


def confirmation_keyboard(pending):
    selected = pending["selected"]
    buttons = [(f"{'✓' if i in selected else '○'} Утверждение {i + 1}", action(pending, f"select.{i}"))
               for i in range(len(pending["owned"]["candidates"]))]
    return keyboard([*buttons, ("Подтвердить данные сайта", action(pending, "confirm")),
        ("Ввести сведения вручную", action(pending, "manual")), ("Отмена", action(pending, "cancel"))])


async def prompt_confirmation(message, state, pending, owned):
    pending.update(owned=owned.model_dump(mode="json"), selected=[], phase="confirmation")
    await save(state, pending, renew=True)
    for i, candidate in enumerate(owned.candidates, 1):
        await send_text(message, f"{i}. На сайте указано: {candidate.statement}\nИсточник: {candidate.source_url}")
    await send_text(message, "Это утверждения сайта, а не проверенные факты. Выберите только те, которые можете подтвердить, затем нажмите «Подтвердить данные сайта».",
                    reply_markup=confirmation_keyboard(pending))


ERRORS = {
    "unavailable": "Не удалось связаться с сервером. Повторите запрос позже.",
    "auth": "Не удалось подключиться к сервису: требуется проверка настройки доступа. Сообщите администратору.",
    "not_found": "Результат не найден.",
    "invalid_state": "Не удалось принять данные запроса. Начните новый запрос: /new",
    "temporary": "Сервис временно недоступен. Можно повторить запрос чуть позже.",
    "server": "Ошибка сервиса. Попробуйте позже.",
    "invalid_response": "Не удалось прочитать ответ сервиса. Попробуйте позже.",
    "request_conflict": "Этот запрос уже был запущен с другим контекстом. Начните новый запрос.",
}


async def error(message, state, pending, exc):
    if exc.category == "confirmation_changed":
        pending["payload"].pop("confirmation", None)
        await send_text(message, "Содержимое сайта изменилось или повторное извлечение отличается. Подтвердите сведения заново.")
        if exc.owned_site and exc.owned_site.snapshot_id and exc.owned_site.candidates:
            await prompt_confirmation(message, state, pending, exc.owned_site)
        else:
            pending["fields"] = ["product_truth"]
            await prompt_fields(message, state, pending)
        return
    pending["phase"] = "retry" if exc.category in {"unavailable", "temporary", "server", "invalid_response"} else "stopped"
    await save(state, pending, renew=True)
    buttons = [("Повторить", action(pending, "retry"))] if pending["phase"] == "retry" else []
    buttons += [("Начать новый запрос", action(pending, "new")), ("Отмена", action(pending, "cancel"))]
    await send_text(message, ERRORS[exc.category], reply_markup=keyboard(buttons))


async def execute(message, actor, state, pending):
    pending["phase"] = "execute"
    await save(state, pending, renew=True)
    try:
        payload = dto.ExecuteRequest.model_validate(pending["payload"])
        response = await client.execute(actor, payload)
    except ValidationError:
        await error(message, state, pending, CopilotError("invalid_state"))
        return
    except CopilotError as exc:
        await error(message, state, pending, exc)
        return
    if isinstance(response, dto.NeedsInputResponse):
        pending["requirements"] = response.model_dump(mode="json")
        # Alternatives are OR groups, not a union of every module's questions.
        pending["fields"] = list(dict.fromkeys(response.alternatives[0])) or ["request_context"]
        owned = response.owned_site
        if owned and owned.outcome != "ACQUIRED":
            await send_text(message, {
                "UNSAFE_SOURCE": "Эту ссылку нельзя использовать как источник. Введите сведения о продукте вручную.",
                "SOURCE_UNAVAILABLE": "Сайт недоступен. Введите сведения о продукте вручную.",
                "EMPTY_CONTENT": "На странице не удалось найти сведения о продукте. Введите их вручную.",
                "CAPABILITY_UNAVAILABLE": "Извлечение сведений сайта временно недоступно. Введите их вручную.",
                "INVALID_EXTRACTION": "Не удалось надёжно извлечь сведения сайта. Введите их вручную.",
            }[owned.outcome])
        if owned and owned.snapshot_id and owned.candidates and "product_truth" in pending["fields"]:
            await prompt_confirmation(message, state, pending, owned)
        elif all(render.ALIASES.get(k, k) in dto.BusinessContext.model_fields for k in pending["fields"]):
            await prompt_fields(message, state, pending, grouped=True)
        else:
            pending["phase"] = "rewrite"
            await save(state, pending, renew=True)
            groups = ["; ".join(render.FIELDS.get(k, "Уточните задачу и исходные данные.") for k in group)
                      for group in response.alternatives]
            text = "Чтобы продолжить, пришлите уточнённый запрос:\n" + "\nИЛИ\n".join(groups)
            if any(k in {"budget", "traffic", "cpl", "cpc"} for group in response.alternatives for k in group):
                text += "\nНапример: Рассчитай лиды при бюджете 10000 и CPL 500"
            await send_text(message, text, reply_markup=keyboard([("Отмена", action(pending, "cancel"))]))
        return
    if isinstance(response, dto.StartedResponse):
        # Keep references only. No local copy of authoritative workflow status.
        await state.update_data(copilot_run={"run_id": response.run_id, "status_url": response.status_url,
            "request_key": payload.request_key})
        await finish(state)
        await send_text(message, "Начал собирать стратегию. Анализ выполняется по шагам.", reply_markup=status_keyboard(response.run_id))
        return
    await finish(state)
    if isinstance(response, dto.ConversationResponse):
        from bot.handlers.chat import _send_to_backend
        await _send_to_backend(message, payload.message, actor_id=actor)
    else:
        sections = render.calculation(response.calculation) if isinstance(response, dto.DirectResponse) else render.module(response.result)
        for section in sections:
            if section:
                await send_text(message, section)


async def receive(message, state: FSMContext):
    actor = message.from_user.id
    if message.chat.type != "private":
        await send_text(message, "Для работы с бизнес-контекстом откройте личный чат с ботом.")
        return
    if await seen(state, f"m:{message.message_id}"):
        return
    pending = (await state.get_data()).get("copilot_pending")
    if pending is None:
        pending = dict(payload={"request_key": request_key(actor, message.chat.id, message.message_id),
            "message": message.text, "context": {}, "competitor_urls": [], "market_source_urls": [], "market_sources": []},
            original_message=message.text, revision=0, fields=[], requirements=None, classified_urls=[], urls=[])
    elif pending["phase"] not in {"fields", "rewrite"}:
        await send_text(message, "Продолжите с помощью кнопок выше или начните новый запрос: /new")
        return
    new_urls = [url for url in urls(message) if url not in pending["classified_urls"]]
    if any(len(url) > 2048 for url in new_urls) or len(new_urls) > 20:
        await send_text(message, "Пришлите не более 20 ссылок, каждая не длиннее 2048 символов.")
        return
    if new_urls:
        pending["urls"] = new_urls
        await prompt_urls(message, state, pending)
        return
    if pending.get("phase") == "fields":
        if not message.text.strip() or len(message.text) > 4000:
            await send_text(message, "Нужен непустой ответ длиной до 4000 символов.")
            return
        field = pending["fields"].pop(0)
        pending["payload"]["context"][render.ALIASES.get(field, field)] = message.text
        if pending["fields"]:
            await prompt_fields(message, state, pending)
            return
    elif pending.get("phase") == "rewrite":
        # API v1's deterministic calculator reads the whole message, not context.
        pending["payload"]["message"] = message.text
    await execute(message, actor, state, pending)


async def reset(message, state, *, cancel=False):
    data = await state.get_data()
    await finish(state)
    if cancel and data.get("copilot_run"):
        await send_text(message, "Уточнения отменены. Уже запущенный анализ нельзя отменить из Telegram v1.")
    else:
        await send_text(message, "Запрос отменён." if cancel else "Напишите новый запрос одним сообщением.")


async def callback_action(callback, state):
    message = callback.message
    if message is None or message.chat.type != "private":
        await callback.answer("Откройте личный чат с ботом.")
        return
    pieces = callback.data.split(":")
    pending = (await state.get_data()).get("copilot_pending")
    if len(pieces) != 3 or not pending or pieces[1] != pending["token"] or await seen(state, f"c:{callback.id}"):
        await callback.answer("Действие устарело. Начните новый запрос: /new")
        return
    await callback.answer()
    name = pieces[2]
    if name in {"new", "cancel"}:
        await reset(message, state, cancel=name == "cancel")
    elif name == "retry" and pending["phase"] == "retry":
        await execute(message, callback.from_user.id, state, pending)
    elif pending["phase"] == "urls" and name in {"own", "competitor", "market", "skip"}:
        url = pending["urls"][0]
        payload = pending["payload"]
        if name in {"competitor", "market"}:
            key = "competitor_urls" if name == "competitor" else "market_source_urls"
            values = payload[key]
            if url not in values and len(values) >= 3:
                await send_text(message, "Можно использовать максимум 3 конкурента и 3 источника рынка. Выберите другую роль или не используйте ссылку.")
                return
            if url not in values:
                values.append(url)
        elif name == "own":
            if payload.get("owned_site_url") and payload["owned_site_url"] != url:
                await send_text(message, "Свой сайт уже выбран. Для другого сайта начните новый запрос: /new")
                return
            payload["owned_site_url"] = url
        pending["classified_urls"].append(url)
        pending["urls"].pop(0)
        if pending["urls"]:
            await prompt_urls(message, state, pending)
        else:
            await execute(message, callback.from_user.id, state, pending)
    elif pending["phase"] == "confirmation":
        if re.fullmatch(r"select\.[0-9]{1,2}", name):
            index = int(name.split(".")[1])
            if index >= len(pending["owned"]["candidates"]):
                return
            selected = pending["selected"]
            selected.remove(index) if index in selected else selected.append(index)
            await save(state, pending)
            await message.edit_reply_markup(reply_markup=confirmation_keyboard(pending))
        elif name == "manual":
            pending["payload"].pop("confirmation", None)
            pending["fields"] = ["product_truth"]
            await prompt_fields(message, state, pending)
        elif name == "confirm":
            if not pending["selected"]:
                await send_text(message, "Сначала выберите хотя бы одно утверждение или введите сведения вручную.")
                return
            pending["payload"]["confirmation"] = {
                "snapshot_id": pending["owned"]["snapshot_id"],
                "statement_ids": [pending["owned"]["candidates"][i]["statement_id"] for i in sorted(pending["selected"])],
                "confirmed": True,
                "reference": "tg-confirm:" + hashlib.sha256(callback.id.encode()).hexdigest(),
            }
            await execute(message, callback.from_user.id, state, pending)


async def status(message, actor, run_id):
    try:
        response = await client.run(actor, run_id)
    except CopilotError as exc:
        await send_text(message, ERRORS.get(exc.category, ERRORS["server"]))
        return
    sections = render.run(response)
    markup = status_keyboard(run_id) if response.status in {dto.RunStatus.QUEUED, dto.RunStatus.RUNNING} else None
    for i, section in enumerate(sections):
        await send_text(message, section, reply_markup=markup if i == len(sections) - 1 else None)
