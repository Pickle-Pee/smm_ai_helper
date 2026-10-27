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
SECTION_KEYS = ("goal", "inputs", "principle", "rationale", "alternatives", "limitations", "verification", "takeaway")


class MentorStates(StatesGroup):
    question = State()


async def show_case(message, actor, run_id, state):
    try:
        data = await backend.request("POST", f"/copilot/runs/{run_id}/mentor", actor)
        sections = data["sections"]
        if (data.get("schema_version") != "case_mentor.v1" or data.get("run_id") != run_id
                or data.get("status") != "COMPLETED" or len(sections) != 8
                or tuple(section["key"] for section in sections) != SECTION_KEYS):
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
    # Old explanation keyboards remain read-only. Only a fresh versioned
    # project activation can change the durable selection.
    from bot.project_navigation import callback, inline
    await send_text(message, "Сохранённый разбор открыт. Чтобы продолжить диалог, откройте карточку и нажмите «Продолжить работу».\n"
                    "/case_feedback сработало | наблюдения | метрики — сохранить обратную связь в активной стратегии.",
                    reply_markup=inline([("Открыть карточку проекта", callback("c", "g:" + run_id))]))


async def selected_run(message, state):
    from bot.project_navigation import binding
    current = await binding(message.from_user.id, message.chat.id)
    active = current.get("active")
    if active is not None:
        return active["source_id"] if active.get("source_type") == "graph" else None
    # Read access to pre-upgrade FSM case history is retained. New explanation
    # callbacks never set this local field, and it never overrides a project.
    return ((await state.get_data()).get("mentor_run_id")
            if await state.get_state() == MentorStates.question.state else None)


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
    try:
        run_id = await selected_run(message, state)
    except (backend.BackendError, ValueError, KeyError, TypeError):
        await send_text(message, "Не удалось проверить активный проект. Обновите текущий контекст.")
        return
    pieces = message.text.split(maxsplit=1)
    fields = [s.strip() for s in pieces[1].split("|")] if len(pieces) == 2 else []
    if fields:
        fields[0] = FEEDBACK_OUTCOMES.get(fields[0].casefold(), fields[0])
    if not run_id or len(fields) not in {2, 3} or fields[0] not in {"applied", "hypothesis_tested", "worked", "did_not_work", "corrected"} or not fields[1]:
        await send_text(message, "В истории выберите стратегию и нажмите «Продолжить работу», затем: /case_feedback сработало | наблюдения | метрики (необязательно).")
        return
    try:
        payload = {
            "request_key": f"tg:{message.from_user.id}:{message.chat.id}:{message.message_id}",
            "outcome": fields[0], "notes": fields[1], "metrics": fields[2] if len(fields) == 3 else ""}
        saved = await backend.request("POST", f"/copilot/runs/{run_id}/mentor/feedback", message.from_user.id, payload=payload)
        if (saved.get("schema_version") != "case_feedback.v1" or saved.get("run_id") != run_id
                or saved.get("verification") != "user_reported"
                or any(saved.get(key) != payload[key] for key in ("outcome", "notes", "metrics"))):
            raise ValueError()
        await send_text(message, "Обратная связь сохранена как ваше сообщение о результате; это не независимая проверка эффективности. Профиль бизнеса не изменён.")
        analysis = saved.get("analysis", {})
        if isinstance(analysis, dict):
            labels = {"cost_per_lead": "Стоимость заявки", "cost_per_sale": "Стоимость привлечения продажи",
                      "lead_to_sale_conversion": "Конверсия заявки в продажу"}
            calculations = analysis.get("calculations", {})
            clarifications = analysis.get("clarifications", [])
            if isinstance(calculations, dict) and isinstance(clarifications, list):
                lines = [labels[key] + ": " + value for key, value in calculations.items() if key in labels and isinstance(value, str)]
                lines.extend(value for value in clarifications if isinstance(value, str))
                if lines:
                    await send_text(message, "Пользовательские данные (не независимо проверено):\n" + "\n".join(lines))
    except (backend.BackendError, AttributeError, TypeError, ValueError):
        await send_text(message, "Не удалось подтвердить сохранение обратной связи. Она могла сохраниться; проверьте следующий ответ наставника перед повтором.")


@router.message(Command("case_history"))
async def history(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return
    try:
        run_id = await selected_run(message, state)
    except (backend.BackendError, ValueError, KeyError, TypeError):
        await send_text(message, "Не удалось проверить активный проект. Обновите текущий контекст.")
        return
    if not run_id:
        await send_text(message, "В истории выберите стратегию и нажмите «Продолжить работу».")
        return
    try:
        data = await backend.request("GET", f"/copilot/runs/{run_id}/mentor/questions", message.from_user.id)
        if data.get("schema_version") != "case_mentor_history.v1" or data.get("run_id") != run_id:
            raise ValueError()
        turns = data["turns"]
        if not isinstance(turns, list):
            raise ValueError()
        texts = []
        for turn in turns:
            question, values = turn["question"], turn["answer"]["paragraphs"]
            if not isinstance(question, str) or not isinstance(values, list) or not all(isinstance(p, str) for p in values):
                raise ValueError()
            texts.append("Вы: " + question + "\nНаставник: " + "\n".join(values))
        for text in texts:
            await send_text(message, text)
        await send_text(message, "Продолжите разбор новым вопросом." if texts else "В этом кейсе пока нет сохранённых ответов. Задайте вопрос.")
    except (backend.BackendError, KeyError, TypeError, ValueError, AttributeError):
        await send_text(message, "Не удалось открыть историю. Повторите /case_history позже.")


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
        if (data.get("schema_version") != "case_mentor_answer.v1" or data.get("run_id") != run_id
                or data.get("question") != message.text.strip()
                or not isinstance(paragraphs, list) or not paragraphs or not all(isinstance(p, str) for p in paragraphs)):
            raise ValueError()
        await send_text(message, "\n\n".join(paragraphs))
    except (backend.BackendError, KeyError, TypeError, ValueError):
        await send_text(message, "Не удалось подтвердить ответ. Он мог сохраниться: проверьте /case_history. "
                        "При неизвестном исходе этот запрос автоматически не запускается повторно. "
                        "Новый вопрос может потребовать нового вызова модели. Стратегия доступна через /copilot_runs.")
