"""Explicitly injected implementations, separate from product metadata."""
from __future__ import annotations

from dataclasses import dataclass
from inspect import iscoroutinefunction
from types import MappingProxyType
from typing import Iterable

from app.module_registry import ModuleId
from app.module_registry.types import validate_executor_key

from .contracts import ModuleExecutor
from .errors import DuplicateExecutorError, ExecutorRegistrationError, UnknownExecutorError


@dataclass(frozen=True, slots=True)
class _Metadata:
    executor_key: str
    module_id: ModuleId
    contract_version: str


def _metadata(executor: ModuleExecutor) -> _Metadata:
    try:
        key = validate_executor_key(executor.executor_key)
        module_id = executor.module_id
        version = executor.contract_version
        operation = executor.execute
    except (AttributeError, ValueError) as exc:
        raise ExecutorRegistrationError("executor requires a valid executor_key and metadata") from exc
    if type(module_id) is not ModuleId:
        raise ExecutorRegistrationError("executor module_id must be ModuleId")
    if type(version) is not str or not version.strip() or len(version) > 128:
        raise ExecutorRegistrationError("executor contract_version must be a non-empty exact string")
    if not iscoroutinefunction(operation):
        raise ExecutorRegistrationError("executor execute must be an async operation")
    return _Metadata(key, module_id, version)


class ModuleExecutorRegistry:
    """No defaults, discovery, aliases, imports or execution during lookup."""

    def __init__(self, executors: Iterable[ModuleExecutor] = ()) -> None:
        registrations = {}
        for executor in executors:
            metadata = _metadata(executor)
            if metadata.executor_key in registrations:
                raise DuplicateExecutorError(f"duplicate executor_key: {metadata.executor_key}")
            registrations[metadata.executor_key] = (metadata, executor)
        self._registrations = MappingProxyType(registrations)

    def resolve(self, executor_key: str) -> ModuleExecutor:
        try:
            validate_executor_key(executor_key)
        except ValueError as exc:
            raise ExecutorRegistrationError("invalid executor_key lookup") from exc
        try:
            metadata, executor = self._registrations[executor_key]
        except KeyError as exc:
            raise UnknownExecutorError(f"unknown executor_key: {executor_key}") from exc
        if _metadata(executor) != metadata:
            raise ExecutorRegistrationError("registered executor metadata changed")
        return executor
