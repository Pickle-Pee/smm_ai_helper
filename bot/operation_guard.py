"""Keep control commands responsive without releasing an in-flight FSM lock."""
import asyncio

from aiogram import BaseMiddleware

from bot.rendering import send_text


class OperationGuard(BaseMiddleware):
    def __init__(self):
        self.counts = {}
        self.tasks = set()

    async def close(self):
        tasks = tuple(self.tasks - {asyncio.current_task()})
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def __call__(self, handler, event, data):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            return await self._handle(handler, event, data)
        finally:
            self.tasks.discard(task)

    async def _handle(self, handler, event, data):
        message = event.message
        callback = event.callback_query
        actor = message.from_user if message else callback.from_user if callback else None
        chat = message.chat if message else callback.message.chat if callback and callback.message else None
        if not actor or not chat:
            return await handler(event, data)
        key = (chat.id, actor.id)
        if message and message.chat.type == "private" and message.text and message.text.strip():
            from bot.project_navigation import MENU_TEXTS, NEW, navigate
            command = message.text.split(maxsplit=1)[0].split("@")[0]
            if key in self.counts and (command in {"/new", "/cancel"} or message.text == NEW):
                await send_text(message, "Предыдущий запрос ещё обрабатывается. Остановка из Telegram сейчас недоступна; "
                                "запрос мог быть принят сервером. Найти сохранённый результат: /copilot_runs или /runs. "
                                "После ответа отправьте /new, чтобы начать новый запрос.")
                return
            if key in self.counts and (message.text in MENU_TEXTS - {NEW}
                    or command in {"/start", "/menu", "/history", "/projects", "/active", "/help"}):
                # Read-only navigation need not wait for the execution's FSM lock.
                # It cannot clear the request or launch a second provider call.
                if message.text == "⬅️ Главное меню" or command in {"/start", "/menu"}:
                    from bot.project_navigation import show_menu
                    await show_menu(message)
                else:
                    await navigate(message, None)
                return
        # A count is required: queued duplicate updates can outlive the first
        # handler. Each entry owns its lifetime until the FSM middleware returns.
        self.counts[key] = self.counts.get(key, 0) + 1
        try:
            return await handler(event, data)
        finally:
            self.counts[key] -= 1
            if not self.counts[key]:
                del self.counts[key]
