"""Internal execution foundation. No production implementations are registered."""
from .contracts import (
    MODULE_EXECUTION_CONTRACT_VERSION,
    ModuleExecutionRequest,
    ModuleExecutionResult,
    ModuleExecutor,
    UpstreamExecutionResult,
)
from .dispatcher import ModuleExecutorDispatcher
from .errors import (
    ContractVersionError,
    DuplicateExecutorError,
    ExecutorRegistrationError,
    ModuleCompatibilityError,
    ModuleExecutionContractError,
    UnknownExecutorError,
)
from .registry import ModuleExecutorRegistry

__all__ = [
    "MODULE_EXECUTION_CONTRACT_VERSION", "ModuleExecutionRequest", "ModuleExecutionResult",
    "ModuleExecutor", "UpstreamExecutionResult", "ModuleExecutorDispatcher", "ModuleExecutorRegistry",
    "ContractVersionError", "DuplicateExecutorError", "ExecutorRegistrationError",
    "ModuleCompatibilityError", "ModuleExecutionContractError", "UnknownExecutorError",
]
