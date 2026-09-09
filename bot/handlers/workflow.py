"""Private-chat commands mapped to the durable backend workflow."""
import re

import httpx
from aiogram import F, Router, types
from aiogram.filters import Command

from app.config import settings
from app.workflows.presentation import render_artifact, delivery_parts
from bot import backend
from bot.rendering import send_text

router = Router()
RUN_ID = re.compile(r"^[0-9a-f]{32}$")


def arguments(text):
    return text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) == 2 else ""


async def private(message):
    if message.chat.type != "private":
        await message.answer("Для работы с бизнес-контекстом откройте личный чат с ботом.")
        return False
    return True


async def display_status(message, data):
    run_id = data["run_id"]
    if data["status"] == "needs_input":
        labels = {"product": "продукт", "audience": "аудиторию", "goal": "цель"}
        fields = ", ".join(labels[x] for x in data["missing_fields"])
        await message.answer(f"Ссылка сохранена. Укажите {fields}:\n/context {run_id} | продукт | аудитория | цель")
    else:
        labels = {"queued": "Принято в работу", "running": "Выполняется", "awaiting_creative": "Анализ готов",
                  "awaiting_mentor": "Креативный пакет готов", "completed": "Все шаги завершены", "failed": "Шаг завершился с ошибкой"}
        await message.answer(f"{labels.get(data['status'], data['status'])}. Результаты сохраняются и доставляются сюда.\n"
                             f"/status {run_id}\n/result {run_id}" + (f"\n{data['error']}" if data.get("error") else ""))
        if any(d["status"] == "failed" for d in data.get("delivery", [])):
            await message.answer(f"Доставку можно повторить без генерации: /redeliver {run_id}")


@router.message(Command("analyze"))
async def analyze(message: types.Message):
    if not await private(message): return
    pieces = [s.strip() for s in arguments(message.text).split("|")]
    if not pieces[0] or len(pieces) > 4:
        await message.answer("/analyze https://конкурент.ru | мой продукт | аудитория | цель\nЕсли профиль /brand уже сохранён, достаточно ссылки.")
        return
    pieces += [""] * (4 - len(pieces))
    try:
        data = await backend.request("POST", "/workflows", message.from_user.id, payload={
            "request_key": f"tg:{message.chat.id}:{message.message_id}", "competitor_url": pieces[0],
            "product": pieces[1], "audience": pieces[2], "goal": pieces[3],
        })
        await display_status(message, data)
    except backend.BackendError as exc:
        await message.answer(str(exc))


@router.message(Command("brand"))
async def brand(message: types.Message):
    if not await private(message): return
    pieces = [s.strip() for s in arguments(message.text).split("|")]
    if len(pieces) not in {3, 4} or not all(pieces[:3]):
        await message.answer("Сохранить профиль бизнеса:\n/brand продукт | аудитория | цель | название (необязательно)")
        return
    payload = {"product_description": pieces[0], "audience": pieces[1], "goals": [pieces[2]]}
    if len(pieces) == 4: payload["brand_name"] = pieces[3]
    try:
        await backend.request("PUT", "/workflows/profile", message.from_user.id, payload=payload)
        await message.answer("Профиль бизнеса сохранён. Начните анализ: /analyze https://конкурент.ru")
    except backend.BackendError as exc:
        await message.answer(str(exc))


@router.message(Command("context"))
async def context(message: types.Message):
    if not await private(message): return
    pieces = [s.strip() for s in arguments(message.text).split("|")]
    if len(pieces) != 4 or not RUN_ID.fullmatch(pieces[0]):
        await message.answer("/context ID_проекта | продукт | аудитория | цель")
        return
    try:
        data = await backend.request("PATCH", f"/workflows/{pieces[0]}/context", message.from_user.id,
                                     payload=dict(zip(("product", "audience", "goal"), pieces[1:])))
        await display_status(message, data)
    except backend.BackendError as exc:
        await message.answer(str(exc))


@router.callback_query(F.data.startswith("mvp:"))
async def continue_workflow(callback: types.CallbackQuery):
    if callback.message is None or not await private(callback.message):
        await callback.answer()
        return
    pieces = callback.data.split(":")
    if len(pieces) != 3 or not RUN_ID.fullmatch(pieces[1]) or pieces[2] not in {"creative", "mentor"}:
        await callback.answer("Некорректное действие", show_alert=True)
        return
    await callback.answer("Проверяю сохранённый проект…")
    try:
        data = await backend.request("POST", f"/workflows/{pieces[1]}/continue", callback.from_user.id,
                                     payload={"action": pieces[2]})
        await display_status(callback.message, data)
    except backend.BackendError as exc:
        await callback.message.answer(str(exc))


@router.message(Command("runs"))
async def runs(message: types.Message):
    if not await private(message): return
    try:
        data = await backend.request("GET", "/workflows", message.from_user.id)
        await send_text(message, "\n".join(f"{r['status']}: /status {r['run_id']}" for r in data) or "Проектов пока нет. Начните с /analyze.")
    except backend.BackendError as exc:
        await message.answer(str(exc))


@router.message(Command("status", "result", "redeliver"))
async def saved_run(message: types.Message):
    if not await private(message): return
    run_id = arguments(message.text)
    if not RUN_ID.fullmatch(run_id):
        await message.answer("Укажите ID проекта после команды. Список проектов: /runs")
        return
    command = message.text.split()[0].split("@")[0]
    try:
        if command == "/redeliver":
            data = await backend.request("POST", f"/workflows/{run_id}/delivery/retry", message.from_user.id)
        else:
            data = await backend.request("GET", f"/workflows/{run_id}", message.from_user.id)
        if command != "/result" or not data["artifacts"]:
            await display_status(message, data)
            return
        for step in ("analysis", "creative", "mentor"):
            artifact = data["artifacts"].get(step)
            if artifact:
                markup = next((part["reply_markup"] for part in delivery_parts(artifact) if "reply_markup" in part), None)
                await send_text(message, render_artifact(artifact), reply_markup=types.InlineKeyboardMarkup.model_validate(markup) if markup else None)
                for image in artifact["images"]:
                    async with httpx.AsyncClient(timeout=20) as client:
                        response = await client.get(settings.API_BASE_URL.rstrip("/") + image["url"], headers=backend.actor_headers(message.from_user.id))
                        response.raise_for_status()
                    await message.answer_photo(types.BufferedInputFile(response.content, filename="creative.png"))
    except (backend.BackendError, httpx.HTTPError):
        await message.answer("Не удалось получить сохранённый результат. Повторите команду позже.")
