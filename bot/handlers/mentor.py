"""Explicit case mentoring through the owner-scoped backend, with restart-safe IDs."""
from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot import backend
from bot.copilot_flow import decode_run
from bot.rendering import send_text

router = Router()
FEEDBACK_OUTCOMES = {"применена": "applied", "проверена": "hypothesis_tested", "сработало": "worked",
                     "не_сработало": "did_not_work", "исправлено": "corrected"}


class MentorStates(StatesGroup):
    question = State()


async def show_case(message, actor, run_id, state):
    try:
        data = await backend.request("POST", f"/copilot/runs/{run_id}/mentor", actor)
        sections = data["sections"]
        if data.get("schema_version") != "case_mentor.v1" or data.get("run_id") != run_id or len(sections) != 8:
            raise ValueError()
        rendered = []
        for section in sections:
            title, paragraphs = section["title"], section["paragraphs"]
            if not isinstance(title, str) or not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
                raise ValueError()
            rendered.append(title + "\n" + "\n".join(paragraphs))
    except (backend.BackendError, KeyError, TypeError, ValueError):
        await send_text(message, "Не удалось открыть разбор. Исходная стратегия доступна через /copilot_runs. Повторите нажатие позже.")
        return
    for text in rendered:
        await send_text(message, text)
    await state.clear()
    await state.update_data(mentor_run_id=run_id)
    await state.set_state(MentorStates.question)
    await send_text(message, "Режим наставника: задайте вопрос об этой стратегии. Разбор использует сохранённые решения.\n"
                    "Для обратной связи: /case_feedback сработало | наблюдения | метрики (необязательно). "
                    "Статусы: применена, проверена, сработало, не_сработало, исправлено.\n/new — выйти и начать новый запрос.")


@router.callback_query(F.data.startswith("cm:"))
async def explain(callback: types.CallbackQuery, state: FSMContext):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer("Откройте личный чат с ботом.")
        return
    try:
        run_id = decode_run("cs:" + callback.data[3:])
    except ValueError:
        await callback.answer("Результат не найден.")
        return
    await callback.answer("Открываю сохранённый разбор…")
    await show_case(callback.message, callback.from_user.id, run_id, state)


@router.message(Command("case_feedback"))
async def feedback(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        await send_text(message, "Откройте личный чат с ботом.")
        return
    run_id = (await state.get_data()).get("mentor_run_id")
    pieces = message.text.split(maxsplit=1)
    fields = [s.strip() for s in pieces[1].split("|")] if len(pieces) == 2 else []
    if fields:
        fields[0] = FEEDBACK_OUTCOMES.get(fields[0].casefold(), fields[0])
    if await state.get_state() != MentorStates.question.state or not run_id or len(fields) not in {2, 3} or fields[0] not in {"applied", "hypothesis_tested", "worked", "did_not_work", "corrected"} or not fields[1]:
        await send_text(message, "Откройте разбор стратегии и укажите: /case_feedback сработало | наблюдения | метрики (необязательно).")
        return
    try:
        await backend.request("POST", f"/copilot/runs/{run_id}/mentor/feedback", message.from_user.id, payload={
            "request_key": f"tg:{message.from_user.id}:{message.chat.id}:{message.message_id}",
            "outcome": fields[0], "notes": fields[1], "metrics": fields[2] if len(fields) == 3 else ""})
        await send_text(message, "Обратная связь сохранена как ваше сообщение о результате; это не независимая проверка эффективности. Профиль бизнеса не изменён.")
    except backend.BackendError:
        await send_text(message, "Не удалось сохранить обратную связь. Повторите команду позже.")


@router.message(StateFilter(MentorStates.question), F.text, ~F.text.startswith("/"))
async def question(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return
    run_id = (await state.get_data()).get("mentor_run_id")
    if not run_id:
        await state.clear()
        await send_text(message, "Снова откройте сохранённую стратегию через /copilot_runs и нажмите «Объяснить решение».")
        return
    try:
        data = await backend.request("POST", f"/copilot/runs/{run_id}/mentor/questions", message.from_user.id, payload={
            "request_key": f"tg:{message.from_user.id}:{message.chat.id}:{message.message_id}", "question": message.text})
        paragraphs = data["paragraphs"]
        if data.get("run_id") != run_id or not isinstance(paragraphs, list) or not paragraphs or not all(isinstance(p, str) for p in paragraphs):
            raise ValueError()
        await send_text(message, "\n\n".join(paragraphs))
    except (backend.BackendError, KeyError, TypeError, ValueError):
        await send_text(message, "Не удалось получить ответ. Сохранённая стратегия и разбор доступны через /copilot_runs.")
