"""Runtime-neutral server-owned budgets; never public or persisted request fields."""
from enum import Enum


class ModuleOutputBudget(Enum):
    # Include a profile identity so equally sized budgets do not become aliases.
    GENERIC = ("generic", 4000)
    POSITIONING_FULL = ("positioning_full", 16000)
    VIRTUAL_CMO = ("virtual_cmo", 16000)


def module_output_tokens(budget: ModuleOutputBudget) -> int:
    if type(budget) is not ModuleOutputBudget:
        raise TypeError("Expected server-owned module output budget")
    return budget.value[1]
