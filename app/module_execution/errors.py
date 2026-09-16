"""Boundary errors only. Executor/provider failures propagate unchanged."""


class ModuleExecutionContractError(ValueError):
    """An execution request or result violates the typed contract."""


class ExecutorRegistrationError(ValueError):
    """An implementation has invalid or unstable metadata/operation."""


class DuplicateExecutorError(ExecutorRegistrationError):
    """More than one implementation uses the same exact key."""


class UnknownExecutorError(LookupError):
    """No implementation was explicitly registered for this exact key."""


class ContractVersionError(ModuleExecutionContractError):
    """Binding and executor must use the supported execution contract."""


class ModuleCompatibilityError(ModuleExecutionContractError):
    """Request, executor and result must agree on the exact ModuleId."""
