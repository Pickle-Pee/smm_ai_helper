"""Safe domain errors; never include context or provider response values."""


class RuntimeContractError(ValueError):
    pass


class CompilationError(RuntimeContractError):
    pass


class StartIdentityConflict(RuntimeContractError):
    pass
