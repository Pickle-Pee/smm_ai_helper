from __future__ import annotations

import json
import re
from importlib.resources import files
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from app.services.agent_registry import AgentRegistry

from .types import (
    ExecutionBinding,
    InputRequirement,
    ModuleAvailabilityStatus,
    ModuleDescriptor,
    ModuleId,
    ModuleType,
    ToolCapability,
)

REGISTRY_VERSION = "1.0.0"
_SEPARATOR_RE = re.compile(r"[\s_-]+", re.UNICODE)


class ModuleRegistryError(ValueError):
    """The module registry resource is invalid and cannot be used."""


class ModuleRegistryNotFoundError(LookupError):
    """A canonical module ID or alias is not registered."""


def normalize_lookup_key(value: str) -> str:
    if not isinstance(value, str):
        raise ModuleRegistryError("module lookup key must be a string")
    normalized = _SEPARATOR_RE.sub("_", value.strip().casefold())
    if not normalized:
        raise ModuleRegistryError("module lookup key must not be empty")
    return normalized


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModuleRegistryError(f"{field} must be a non-empty string")
    return value.strip()


def _require_texts(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ModuleRegistryError(f"{field} must be a{' non-empty' if not allow_empty else ''} list")
    return tuple(_require_text(item, field) for item in value)


class ModuleRegistry:
    """Read-only, side-effect-free product module metadata registry."""

    def __init__(
        self,
        *,
        version: str,
        descriptors: Iterable[ModuleDescriptor],
    ) -> None:
        if version != REGISTRY_VERSION:
            raise ModuleRegistryError(f"unsupported source version: {version!r}")
        descriptor_items = tuple(descriptors)
        expected_ids = frozenset(ModuleId)
        actual_ids = [item.module_id for item in descriptor_items]
        if len(descriptor_items) != len(expected_ids):
            raise ModuleRegistryError("registry must contain exactly fifteen descriptors")
        if len(set(actual_ids)) != len(actual_ids):
            raise ModuleRegistryError("duplicate canonical module ID")
        actual_set = frozenset(actual_ids)
        if actual_set != expected_ids:
            missing = sorted(item.value for item in expected_ids - actual_set)
            unexpected = sorted(str(item) for item in actual_set - expected_ids)
            raise ModuleRegistryError(f"invalid canonical ID set; missing={missing}, unexpected={unexpected}")

        by_id = {descriptor.module_id: descriptor for descriptor in descriptor_items}
        known_agents = AgentRegistry.supported_agent_types()
        for descriptor in descriptor_items:
            self._validate_descriptor(descriptor, expected_ids, known_agents)
        if any(descriptor.execution_binding is not None for descriptor in descriptor_items):
            raise ModuleRegistryError("registry version 1.0.0 must contain zero execution bindings")

        lookup: dict[str, ModuleDescriptor] = {}
        canonical_keys = {normalize_lookup_key(item.value): item for item in expected_ids}
        for key, module_id in canonical_keys.items():
            if key in lookup:
                raise ModuleRegistryError("ambiguous canonical module ID")
            lookup[key] = by_id[module_id]
        for descriptor in descriptor_items:
            seen_aliases: set[str] = set()
            for alias in descriptor.aliases:
                key = normalize_lookup_key(alias)
                if key in seen_aliases:
                    raise ModuleRegistryError(f"duplicate alias for {descriptor.module_id.value}: {alias!r}")
                seen_aliases.add(key)
                if key in canonical_keys:
                    raise ModuleRegistryError(f"alias collides with canonical module ID: {alias!r}")
                if key in lookup:
                    raise ModuleRegistryError(f"ambiguous normalized alias: {alias!r}")
                lookup[key] = descriptor

        self._version = version
        self._descriptors = descriptor_items
        self._by_id: Mapping[ModuleId, ModuleDescriptor] = MappingProxyType(by_id)
        self._lookup: Mapping[str, ModuleDescriptor] = MappingProxyType(lookup)

    @classmethod
    def load(cls, version: str = REGISTRY_VERSION) -> "ModuleRegistry":
        if version != REGISTRY_VERSION:
            raise ModuleRegistryError(f"unsupported registry version: {version!r}")
        resource = files("app.module_registry").joinpath(f"v{version}.json")
        try:
            raw = json.loads(resource.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModuleRegistryError(f"cannot load module registry v{version}") from exc
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ModuleRegistry":
        if not isinstance(raw, Mapping):
            raise ModuleRegistryError("registry resource must be an object")
        version = _require_text(raw.get("source_version"), "source_version")
        rows = raw.get("modules")
        if not isinstance(rows, list):
            raise ModuleRegistryError("modules must be a list")
        descriptors = tuple(cls._parse_descriptor(row, index) for index, row in enumerate(rows))
        return cls(version=version, descriptors=descriptors)

    @staticmethod
    def _parse_descriptor(raw: Any, index: int) -> ModuleDescriptor:
        if not isinstance(raw, Mapping):
            raise ModuleRegistryError(f"modules[{index}] must be an object")
        field = lambda name: f"modules[{index}].{name}"
        try:
            module_id = ModuleId(_require_text(raw.get("module_id"), field("module_id")))
            module_types = tuple(ModuleType(item) for item in _require_texts(raw.get("module_types"), field("module_types")))
            inputs_raw = raw.get("inputs")
            if not isinstance(inputs_raw, Mapping):
                raise ModuleRegistryError(f"{field('inputs')} must be an object")
            expected_input_keys = {item.value for item in InputRequirement}
            if set(inputs_raw) != expected_input_keys:
                raise ModuleRegistryError(f"{field('inputs')} must contain every requirement classification")
            inputs = {
                requirement: _require_texts(inputs_raw[requirement.value], field(f"inputs.{requirement.value}"), allow_empty=True)
                for requirement in InputRequirement
            }
            binding_raw = raw.get("execution_binding")
            binding = None
            if binding_raw is not None:
                if not isinstance(binding_raw, Mapping):
                    raise ModuleRegistryError(f"{field('execution_binding')} must be an object or null")
                binding = ExecutionBinding(
                    agent_id=_require_text(binding_raw.get("agent_id"), field("execution_binding.agent_id")),
                    compatibility=_require_text(binding_raw.get("compatibility"), field("execution_binding.compatibility")),
                    evidence=_require_text(binding_raw.get("evidence"), field("execution_binding.evidence")),
                )
            return ModuleDescriptor(
                module_id=module_id,
                module_types=module_types,
                purpose=_require_text(raw.get("purpose"), field("purpose")),
                use_when=_require_texts(raw.get("use_when"), field("use_when")),
                do_not_use_when=_require_texts(raw.get("do_not_use_when"), field("do_not_use_when")),
                inputs=inputs,
                outputs=_require_texts(raw.get("outputs"), field("outputs")),
                supported_tools=frozenset(ToolCapability(item) for item in _require_texts(raw.get("supported_tools"), field("supported_tools"), allow_empty=True)),
                quality_gate=_require_texts(raw.get("quality_gate"), field("quality_gate")),
                handoffs=tuple(ModuleId(item) for item in _require_texts(raw.get("handoffs"), field("handoffs"), allow_empty=True)),
                aliases=_require_texts(raw.get("aliases"), field("aliases"), allow_empty=True),
                authority_limitations=_require_texts(raw.get("authority_limitations"), field("authority_limitations")),
                availability_status=ModuleAvailabilityStatus(_require_text(raw.get("availability_status"), field("availability_status"))),
                execution_binding=binding,
            )
        except ValueError as exc:
            raise ModuleRegistryError(f"invalid enum value in modules[{index}]: {exc}") from exc

    @staticmethod
    def _validate_descriptor(descriptor: ModuleDescriptor, expected_ids: frozenset[ModuleId], known_agents: set[str]) -> None:
        if not descriptor.module_types:
            raise ModuleRegistryError(f"{descriptor.module_id.value} has no module type")
        if descriptor.module_id in descriptor.handoffs:
            raise ModuleRegistryError(f"{descriptor.module_id.value} has a prohibited self-handoff")
        missing_handoffs = set(descriptor.handoffs) - expected_ids
        if missing_handoffs:
            raise ModuleRegistryError(f"{descriptor.module_id.value} has unknown handoff targets")
        binding = descriptor.execution_binding
        if descriptor.availability_status is ModuleAvailabilityStatus.METADATA_ONLY and binding is not None:
            raise ModuleRegistryError("metadata-only module cannot declare an execution binding")
        if descriptor.availability_status is ModuleAvailabilityStatus.EXECUTION_BOUND and binding is None:
            raise ModuleRegistryError("execution-bound module requires an execution binding")
        if binding is not None:
            if binding.compatibility != "exact":
                raise ModuleRegistryError("execution binding requires exact compatibility")
            if binding.agent_id not in known_agents:
                raise ModuleRegistryError(f"execution binding targets unknown agent: {binding.agent_id}")

    @property
    def version(self) -> str:
        return self._version

    @property
    def descriptors(self) -> tuple[ModuleDescriptor, ...]:
        return self._descriptors

    def get(self, module_id_or_alias: str | ModuleId) -> ModuleDescriptor:
        value = module_id_or_alias.value if isinstance(module_id_or_alias, ModuleId) else module_id_or_alias
        key = normalize_lookup_key(value)
        try:
            return self._lookup[key]
        except KeyError as exc:
            raise ModuleRegistryNotFoundError(f"unknown module ID or alias: {value!r}") from exc
