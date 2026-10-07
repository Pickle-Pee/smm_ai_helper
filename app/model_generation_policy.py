"""Runtime-neutral server-owned budgets; never public or persisted request fields."""
from enum import Enum


class ModuleOutputBudget(Enum):
    GENERIC = 4000
    POSITIONING_FULL = 16000


def module_output_tokens(budget: ModuleOutputBudget) -> int:
    if type(budget) is not ModuleOutputBudget:
        raise TypeError("Expected server-owned module output budget")
    return budget.value
