from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧠 Стратегия", callback_data="agent_strategy")
    kb.button(text="✍️ Контент", callback_data="agent_content")
    kb.button(text="📊 Аналитика", callback_data="agent_analytics")
    kb.button(text="📣 Продвижение", callback_data="agent_promo")
    kb.button(text="📈 Тренды", callback_data="agent_trends")
    kb.adjust(2, 2, 1)
    return kb.as_markup()
