"""Runtime-neutral values for one module invocation, with no resource ownership."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol

from app.marketing_orchestrator.contracts import ContextPacket, ImmutableJsonValue, freeze_json_value
from app.marketing_orchestrator.errors import InvalidContextValueError
from app.marketing_orchestrator.quality_gates.contracts import NormalizedModuleResult
from app.module_registry import ModuleId

from .errors import ModuleCompatibilityError, ModuleExecutionContractError

MODULE_EXECUTION_CONTRACT_VERSION = "module_executor.v1"
_ID = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}", re.ASCII)


def _text(value: str, name: str, *, identifier: bool = False) -> str:
    if type(value) is not str or not value.strip():
        raise ModuleExecutionContractError(f"{name} must be a non-empty exact string")
    if identifier and _ID.fullmatch(value) is None:
        raise ModuleExecutionContractError(f"{name} must be a stable identifier of at most 128 characters")
    return value


def _module(value: ModuleId) -> None:
    if type(value) is not ModuleId:
        raise ModuleExecutionContractError("module_id must be an exact ModuleId")


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleExecutionResult:
    module_id: ModuleId
    schema_version: str
    payload: Mapping[str, ImmutableJsonValue]
    normalized_result: NormalizedModuleResult

    def __post_init__(self) -> None:
        _module(self.module_id)
        _text(self.schema_version, "schema_version", identifier=True)
        if type(self.normalized_result) is not NormalizedModuleResult:
            raise ModuleExecutionContractError("normalized_result must be NormalizedModuleResult")
        if self.normalized_result.module_id is not self.module_id:
            raise ModuleCompatibilityError("normalized_result.module_id must match result.module_id")
        # Only exact caller-owned JSON objects enter here. Mapping proxies are
        # output-only, as in the existing Orchestrator context contract.
        if type(self.payload) is not dict:
            raise ModuleExecutionContractError("payload must be an exact JSON object")
        try:
            payload = freeze_json_value(self.payload)
        except (InvalidContextValueError, RecursionError) as exc:
            raise ModuleExecutionContractError("payload must contain finite, acyclic, exact JSON values") from exc
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True, kw_only=True)
class UpstreamExecutionResult:
    """Complete predecessor output; result identity lives in Quality Gates."""

    producer_node_id: str
    result: ModuleExecutionResult

    def __post_init__(self) -> None:
        _text(self.producer_node_id, "producer_node_id", identifier=True)
        if type(self.result) is not ModuleExecutionResult:
            raise ModuleExecutionContractError("upstream result must be ModuleExecutionResult")

    @property
    def result_id(self) -> str:
        return self.result.normalized_result.result_id

    @property
    def module_id(self) -> ModuleId:
        return self.result.module_id


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleExecutionRequest:
    execution_id: str
    module_id: ModuleId
    objective: str
    expected_outputs: tuple[str, ...]
    context_packet: ContextPacket
    upstream_results: tuple[UpstreamExecutionResult, ...] = ()

    def __post_init__(self) -> None:
        _text(self.execution_id, "execution_id", identifier=True)
        _module(self.module_id)
        _text(self.objective, "objective")
        if type(self.expected_outputs) not in (tuple, list) or not self.expected_outputs:
            raise ModuleExecutionContractError("expected_outputs must be a non-empty tuple or list")
        outputs = tuple(_text(item, "expected_outputs item") for item in self.expected_outputs)
        if len(outputs) != len(set(outputs)):
            raise ModuleExecutionContractError("expected_outputs must be unique")
        object.__setattr__(self, "expected_outputs", outputs)
        if type(self.context_packet) is not ContextPacket:
            raise ModuleExecutionContractError("context_packet must be ContextPacket")
        if type(self.upstream_results) not in (tuple, list):
            raise ModuleExecutionContractError("upstream_results must be a tuple or list")
        if any(type(item) is not UpstreamExecutionResult for item in self.upstream_results):
            raise ModuleExecutionContractError("upstream_results must contain UpstreamExecutionResult")
        upstream = tuple(self.upstream_results)
        identities = [item.result_id for item in upstream]
        if len(identities) != len(set(identities)):
            raise ModuleExecutionContractError("upstream result identities must be unique within a request")
        object.__setattr__(self, "upstream_results", upstream)


class ModuleExecutor(Protocol):
    """One exact module implementation with stable, read-only metadata."""

    @property
    def executor_key(self) -> str: ...

    @property
    def module_id(self) -> ModuleId: ...

    @property
    def contract_version(self) -> str: ...

    async def execute(self, request: ModuleExecutionRequest) -> ModuleExecutionResult: ...
