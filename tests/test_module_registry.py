from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import FrozenInstanceError
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

import pytest

import app.module_registry.registry as registry_module
from app.module_registry import (
    ExecutionBinding,
    ModuleActivation,
    ModuleAvailabilityStatus,
    ModuleId,
    ModuleRegistry,
    ModuleRegistryError,
    ModuleRegistryNotFoundError,
    ModuleResultStatus,
    ToolCapability,
)
from app.services.agent_registry import AgentRegistry

EXPECTED_IDS = (
    "VIRTUAL_CMO",
    "BUSINESS_DIAGNOSTICS",
    "MARKET_ANALYSIS",
    "COMPETITOR_ANALYSIS",
    "POSITIONING",
    "AD_AUDIT",
    "CJM",
    "CUSTDEV",
    "CREATOR",
    "COPY_EDITOR",
    "LEAD_MAGNET",
    "TREND_MONITORING",
    "EXPERIMENTS",
    "PROJECT_DEFENSE",
    "MENTOR",
)
EXPECTED_AGENT_IDS = {"strategy", "content", "analytics", "promo", "trends"}
EXPECTED_NORMALIZED_SHA256 = "25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918"


def canonical_mapping() -> dict:
    resource = files("app.module_registry").joinpath("v1.0.0.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def descriptor(raw: dict, module_id: str) -> dict:
    return next(item for item in raw["modules"] if item["module_id"] == module_id)


def test_canonical_registry_resource_and_order_are_stable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = ModuleRegistry.load()

    assert registry.version == "1.0.0"
    assert tuple(item.module_id.value for item in registry.descriptors) == EXPECTED_IDS
    assert len({id(item) for item in registry.descriptors}) == 15
    assert all(item.availability_status is ModuleAvailabilityStatus.METADATA_ONLY for item in registry.descriptors)
    assert all(item.execution_binding is None for item in registry.descriptors)
    assert files("app.module_registry").joinpath("v1.0.0.json").is_file()


def test_canonical_resource_normalized_checksum_is_stable():
    raw = canonical_mapping()
    normalized = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(normalized).hexdigest() == EXPECTED_NORMALIZED_SHA256


def test_descriptor_fields_are_complete_and_typed():
    registry = ModuleRegistry.load()

    for item in registry.descriptors:
        assert item.module_types
        assert item.purpose
        assert item.use_when
        assert item.do_not_use_when
        assert set(item.inputs) == set(registry_module.InputRequirement)
        assert item.inputs[registry_module.InputRequirement.REQUIRED]
        assert item.outputs
        assert item.quality_gate
        assert item.authority_limitations
        assert item.supported_tools <= frozenset(ToolCapability)
        assert item.module_id not in item.handoffs


def test_lookup_normalizes_alias_and_canonical_id_without_copying():
    registry = ModuleRegistry.load()
    canonical = registry.get("POSITIONING")

    assert registry.get("  positioning  ") is canonical
    assert registry.get("positioning") is canonical
    assert registry.get("USP and-offer") is canonical
    assert registry.get("  usp_AND__offer ") is canonical

    with pytest.raises(ModuleRegistryNotFoundError, match="unknown module"):
        registry.get("not-a-module")


def test_registry_and_nested_descriptor_state_are_deeply_immutable():
    registry = ModuleRegistry.load()
    item = registry.get(ModuleId.VIRTUAL_CMO)

    with pytest.raises(FrozenInstanceError):
        item.purpose = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        item.inputs[registry_module.InputRequirement.REQUIRED] = ("changed",)  # type: ignore[index]
    with pytest.raises((AttributeError, TypeError)):
        item.outputs.append("changed")  # type: ignore[attr-defined]
    with pytest.raises((AttributeError, TypeError)):
        registry.descriptors.append(item)  # type: ignore[attr-defined]
    assert registry.get("virtual cmo") is item
    assert item.purpose != "changed"


def test_activation_contract_deep_freezes_context():
    source = {"nested": {"items": ["one"]}}
    activation = ModuleActivation(
        module_id=ModuleId.CREATOR,
        objective="Create",
        user_goal="Campaign",
        relevant_context=source,
    )
    source["nested"]["items"].append("two")

    assert isinstance(activation.relevant_context, MappingProxyType)
    assert activation.relevant_context["nested"]["items"] == ("one",)
    assert set(ModuleResultStatus) == {
        ModuleResultStatus.PASS,
        ModuleResultStatus.PASS_WITH_LIMITATIONS,
        ModuleResultStatus.FAIL,
        ModuleResultStatus.BLOCKED,
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(source_version="2.0.0"), "unsupported source version"),
        (lambda raw: raw["modules"].pop(), "exactly fifteen"),
        (lambda raw: raw["modules"].append(copy.deepcopy(raw["modules"][0])), "exactly fifteen"),
        (lambda raw: raw["modules"][0].update(module_id="UNKNOWN"), "invalid enum value"),
        (lambda raw: raw["modules"][0].update(purpose=""), "non-empty string"),
        (lambda raw: raw["modules"][0].update(module_types=["INVALID"]), "invalid enum value"),
        (lambda raw: raw["modules"][0].update(supported_tools=["telepathy"]), "invalid enum value"),
        (lambda raw: raw["modules"][0].update(handoffs=["UNKNOWN"]), "invalid enum value"),
        (lambda raw: raw["modules"][0].update(handoffs=["VIRTUAL_CMO"]), "self-handoff"),
    ],
)
def test_invalid_resources_fail_before_registry_use(mutate, message):
    raw = canonical_mapping()
    mutate(raw)

    with pytest.raises(ModuleRegistryError, match=message):
        ModuleRegistry.from_mapping(raw)


def test_unexpected_id_is_rejected_independently_of_count():
    raw = canonical_mapping()
    raw["modules"][-1]["module_id"] = "VIRTUAL_CMO"
    with pytest.raises(ModuleRegistryError, match="duplicate canonical"):
        ModuleRegistry.from_mapping(raw)


@pytest.mark.parametrize(
    "aliases",
    [
        ["same alias", "same-alias"],
        ["VIRTUAL-CMO"],
        ["   "],
    ],
)
def test_alias_duplicates_canonical_collisions_and_empty_values_fail(aliases):
    raw = canonical_mapping()
    descriptor(raw, "POSITIONING")["aliases"] = aliases

    with pytest.raises(ModuleRegistryError):
        ModuleRegistry.from_mapping(raw)


def test_ambiguous_aliases_across_descriptors_fail():
    raw = canonical_mapping()
    descriptor(raw, "POSITIONING")["aliases"] = ["shared alias"]
    descriptor(raw, "CREATOR")["aliases"] = ["SHARED-alias"]

    with pytest.raises(ModuleRegistryError, match="ambiguous normalized alias"):
        ModuleRegistry.from_mapping(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"availability_status": "metadata_only", "execution_binding": {"executor_key": "test.cmo", "contract_version": "module_executor.v1", "compatibility": "exact", "evidence": "exact"}},
        {"availability_status": "execution_bound", "execution_binding": None},
        {"availability_status": "execution_bound", "execution_binding": {"executor_key": "test.unknown", "contract_version": "module_executor.v1", "compatibility": "exact", "evidence": "exact"}},
        {"availability_status": "execution_bound", "execution_binding": {"executor_key": "test.cmo", "contract_version": "module_executor.v1", "compatibility": "partial", "evidence": "partial"}},
        {"availability_status": "execution_bound", "execution_binding": {"agent_id": "strategy", "compatibility": "exact", "evidence": "legacy shape"}},
    ],
)
def test_inconsistent_or_unknown_execution_bindings_fail(change):
    raw = canonical_mapping()
    descriptor(raw, "VIRTUAL_CMO").update(change)

    with pytest.raises(ModuleRegistryError):
        ModuleRegistry.from_mapping(raw)


def test_v1_rejects_even_a_valid_generic_execution_binding():
    raw = canonical_mapping()
    descriptor(raw, "VIRTUAL_CMO").update(
        availability_status="execution_bound",
        execution_binding={
            "executor_key": "test.cmo",
            "contract_version": "module_executor.v1",
            "compatibility": "exact",
            "evidence": "hypothetical exact compatibility",
        },
    )

    with pytest.raises(ModuleRegistryError, match="zero execution bindings"):
        ModuleRegistry.from_mapping(raw)


def test_v1_direct_constructor_rejects_bindings_without_runtime_availability_lookup():
    from dataclasses import replace

    registry = ModuleRegistry.load()
    bound = replace(registry.descriptors[0], availability_status=ModuleAvailabilityStatus.EXECUTION_BOUND,
                    execution_binding=ExecutionBinding("unregistered.cmo", "module_executor.v1", "exact", "test"))
    with pytest.raises(ModuleRegistryError, match="zero execution bindings"):
        ModuleRegistry(version="1.0.0", descriptors=(bound, *registry.descriptors[1:]))


def test_metadata_registry_is_disjoint_from_execution_registry_and_has_no_side_effects(monkeypatch):
    assert AgentRegistry.supported_agent_types() == EXPECTED_AGENT_IDS
    assert set(EXPECTED_IDS).isdisjoint(EXPECTED_AGENT_IDS)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("registry lookup must not invoke model or QC behavior")

    monkeypatch.setattr("app.llm.openai_text.chat", forbidden)
    monkeypatch.setattr("app.services.qc_service.QCService.find_issues", forbidden)
    monkeypatch.setattr(AgentRegistry, "supported_agent_types", forbidden)
    monkeypatch.setattr(AgentRegistry, "get_agent_class", forbidden)
    registry = ModuleRegistry.load()
    assert registry.get("creator").module_id is ModuleId.CREATOR


def test_dockerfile_copies_registry_resource_into_repository_deployment():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "WORKDIR /app" in dockerfile
    assert "COPY . ." in dockerfile
    assert (root / "app/module_registry/v1.0.0.json").is_file()
    assert not any(root.glob("pyproject.toml"))


EXECUTABLE_SHA256 = "f6f604db27a123ce66edd61424b1f7f8c4cef68fc6e166ff3723bccb3822029c"


def executable_mapping():
    return json.loads(files("app.module_registry").joinpath("v1.1.0.json").read_text(encoding="utf-8"))


def test_executable_registry_is_explicit_and_preserves_all_canonical_metadata():
    assert ModuleRegistry.load().version == "1.0.0"
    registry = ModuleRegistry.load("1.1.0")
    expected = {ModuleId.COMPETITOR_ANALYSIS: "competitor_analysis.v1", ModuleId.POSITIONING: "positioning.v1", ModuleId.CREATOR: "creator.v1"}
    assert {d.module_id: d.execution_binding.executor_key for d in registry.descriptors if d.execution_binding} == expected
    assert sum(d.availability_status is ModuleAvailabilityStatus.METADATA_ONLY for d in registry.descriptors) == 12
    for descriptor in registry.descriptors:
        if descriptor.module_id in expected:
            assert descriptor.execution_binding.contract_version == "module_executor.v1"
            assert descriptor.execution_binding.compatibility == "exact"
        else:
            assert descriptor.execution_binding is None
    before, after = canonical_mapping(), executable_mapping()
    for old, new in zip(before["modules"], after["modules"]):
        for key in set(old) - {"availability_status", "execution_binding"}:
            assert old[key] == new[key]
    normalized = json.dumps(after, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(normalized).hexdigest() == EXECUTABLE_SHA256


@pytest.mark.parametrize("version", ["1.2.0", "2.0.0", "../1.0.0", "", "latest"])
def test_unapproved_registry_versions_fail_closed(version):
    with pytest.raises(ModuleRegistryError):
        ModuleRegistry.load(version)
    raw = executable_mapping()
    raw["source_version"] = version
    with pytest.raises(ModuleRegistryError):
        ModuleRegistry.from_mapping(raw)


@pytest.mark.parametrize("mutation", ["extra", "missing", "key", "version"])
def test_v11_rejects_every_nonapproved_binding_set(mutation):
    raw = executable_mapping()
    row = descriptor(raw, "CREATOR")
    if mutation == "extra":
        descriptor(raw, "MENTOR").update(availability_status="execution_bound", execution_binding=copy.deepcopy(row["execution_binding"]))
    elif mutation == "missing":
        row.update(availability_status="metadata_only", execution_binding=None)
    else:
        row["execution_binding"]["executor_key" if mutation == "key" else "contract_version"] = "unapproved.v2"
    with pytest.raises(ModuleRegistryError, match="approved"):
        ModuleRegistry.from_mapping(raw)
