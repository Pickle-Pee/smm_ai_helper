"""Thin Telegram bindings for the Copilot HTTP adapter."""
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot import copilot_flow as flow
from bot.rendering import send_text

router = Router()


@router.message(Command("new", "cancel"))
async def new_or_cancel(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        await send_text(message, "Откройте личный чат с ботом.")
        return
    await flow.reset(message, state, cancel=message.text.split()[0].split("@")[0] == "/cancel")


@router.message(Command("copilot_status"))
async def run_status(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        await send_text(message, "Откройте личный чат с ботом.")
        return
    parts = message.text.split(maxsplit=1)
    saved = (await state.get_data()).get("copilot_run") or {}
    run_id = parts[1].strip() if len(parts) == 2 else saved.get("run_id")
    if not run_id:
        await send_text(message, "Нажмите «Проверить готовность» под запущенным запросом или укажите ID после /copilot_status.")
        return
    await flow.status(message, message.from_user.id, run_id)


@router.callback_query(F.data.startswith("cs:"))
async def check_status(callback: types.CallbackQuery):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer("Откройте личный чат с ботом.")
        return
    await callback.answer()
    try:
        run_id = flow.decode_run(callback.data)
    except ValueError:
        await send_text(callback.message, "Результат не найден.")
        return
    await flow.status(callback.message, callback.from_user.id, run_id)


@router.callback_query(F.data.startswith("cp:"))
async def continue_request(callback: types.CallbackQuery, state: FSMContext):
    await flow.callback_action(callback, state)
