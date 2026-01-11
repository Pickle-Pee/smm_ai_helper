from aiogram import Router, types
from aiogram.filters import CommandStart

from bot.keyboards import main_menu_kb

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я рой SMM-агентов.\n\n"
        "Можешь просто написать задачу в свободной форме — я помогу.\n\n"
        "Если нужен старый режим, выбери агента ниже:\n\n"
        "Также ты можешь в любой момент написать /history, чтобы посмотреть последние задачи.",
        reply_markup=main_menu_kb(),
    )
