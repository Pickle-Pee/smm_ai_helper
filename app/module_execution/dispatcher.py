"""A single invocation boundary. Scheduling and retry belong to the caller."""
from app.module_registry import ExecutionBinding

from .contracts import MODULE_EXECUTION_CONTRACT_VERSION, ModuleExecutionRequest, ModuleExecutionResult
from .errors import ContractVersionError, ModuleCompatibilityError, ModuleExecutionContractError
from .registry import ModuleExecutorRegistry


class ModuleExecutorDispatcher:
    def __init__(self, registry: ModuleExecutorRegistry) -> None:
        self._registry = registry

    async def dispatch(self, binding: ExecutionBinding, request: ModuleExecutionRequest) -> ModuleExecutionResult:
        if type(binding) is not ExecutionBinding:
            raise ModuleExecutionContractError("binding must be ExecutionBinding")
        if type(request) is not ModuleExecutionRequest:
            raise ModuleExecutionContractError("request must be ModuleExecutionRequest")
        if binding.compatibility != "exact":
            raise ModuleCompatibilityError("binding requires exact compatibility")
        executor = self._registry.resolve(binding.executor_key)
        if (binding.contract_version != MODULE_EXECUTION_CONTRACT_VERSION
                or executor.contract_version != MODULE_EXECUTION_CONTRACT_VERSION):
            raise ContractVersionError("binding and executor must use module_executor.v1")
        if executor.module_id is not request.module_id:
            raise ModuleCompatibilityError("request.module_id must match executor.module_id")

        result = await executor.execute(request)

        if type(result) is not ModuleExecutionResult:
            raise ModuleExecutionContractError("executor must return ModuleExecutionResult")
        if result.module_id is not request.module_id or result.normalized_result.module_id is not result.module_id:
            raise ModuleCompatibilityError("returned result must match request.module_id")
        return result
