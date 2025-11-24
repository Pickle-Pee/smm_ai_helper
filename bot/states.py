from aiogram.fsm.state import State, StatesGroup


class AgentStates(StatesGroup):
    waiting_task_description = State()
    asking_details = State()
    running_agent = State()
