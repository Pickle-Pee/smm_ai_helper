"""Execution boundary tests: explicitly injected fakes, no providers or ingress."""
import ast
import asyncio
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields
from decimal import Decimal
from itertools import permutations
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType
from unittest.mock import AsyncMock

import pytest

from app.marketing_orchestrator import AuthorizedContextFact, ContextPacket, UpstreamFinding
from app.marketing_orchestrator.quality_gates import (
    AuthorityStatus, ClaimLineageType, ClaimType, Confidence, EvidenceSufficiency,
    NormalizedClaim, NormalizedModuleResult, QualityGateEvaluator,
)
from app.module_execution import (
    MODULE_EXECUTION_CONTRACT_VERSION, ContractVersionError, DuplicateExecutorError,
    ExecutorRegistrationError, ModuleCompatibilityError, ModuleExecutionContractError,
    ModuleExecutionRequest, ModuleExecutionResult, ModuleExecutorDispatcher,
    ModuleExecutorRegistry, UnknownExecutorError, UpstreamExecutionResult,
)
from app.module_registry import ExecutionBinding, ModuleId, ModuleRegistry, ModuleResultStatus

ROOT = Path(__file__).resolve().parents[1]


def normalized(module=ModuleId.CREATOR, identity="res_creator", **overrides):
    values = dict(result_id=identity, module_id=module, module_status=ModuleResultStatus.PASS,
                  evidence_sufficiency=EvidenceSufficiency.SUFFICIENT)
    values.update(overrides)
    return NormalizedModuleResult(**values)


def result(module=ModuleId.CREATOR, **overrides):
    values = dict(module_id=module, schema_version="test.creative.v1", payload={"headline": "A useful offer"},
                  normalized_result=normalized(module))
    values.update(overrides)
    return ModuleExecutionResult(**values)


def request(**overrides):
    values = dict(execution_id="execution.1", module_id=ModuleId.CREATOR, objective="Prepare a creative",
                  expected_outputs=("headline",), context_packet=ContextPacket())
    values.update(overrides)
    return ModuleExecutionRequest(**values)


def binding(**overrides):
    values = dict(executor_key="test.creator.v1", contract_version=MODULE_EXECUTION_CONTRACT_VERSION,
                  compatibility="exact", evidence="Explicit test-only compatibility")
    values.update(overrides)
    return ExecutionBinding(**values)


class FakeExecutor:
    def __init__(self, **overrides):
        self.executor_key = "test.creator.v1"
        self.module_id = ModuleId.CREATOR
        self.contract_version = MODULE_EXECUTION_CONTRACT_VERSION
        self.execute = AsyncMock(return_value=result())
        self.__dict__.update(overrides)


def dispatch(fake, *, declaration=None, invocation=None):
    return asyncio.run(ModuleExecutorDispatcher(ModuleExecutorRegistry([fake])).dispatch(
        binding() if declaration is None else declaration,
        request() if invocation is None else invocation,
    ))


def test_full_predecessor_payload_and_context_are_deeply_frozen_without_caller_aliases():
    source = {"scenes": [{"text": "first", "values": [None, True, 3, 0.5]}]}
    context_source = {"segments": ["small businesses"]}
    facts = [AuthorizedContextFact("fact.product", "Product", context_source)]
    context = ContextPacket(known_facts=facts, upstream_findings=[UpstreamFinding("analysis", "summary", "evidence")])
    predecessor = result(payload=source)
    upstream = [UpstreamExecutionResult(producer_node_id="analysis", result=predecessor)]
    outputs = ["headline"]
    invocation = request(context_packet=context, expected_outputs=outputs, upstream_results=upstream)
    source["scenes"][0]["values"].append("changed")
    context_source["segments"].append("changed")
    facts.clear()
    upstream.clear()
    outputs.append("changed")

    assert invocation.context_packet is context
    assert invocation.expected_outputs == ("headline",)
    saved = invocation.upstream_results[0]
    assert saved.result is predecessor
    assert saved.module_id is ModuleId.CREATOR and saved.result_id == "res_creator"
    assert saved.result.payload["scenes"][0]["values"] == (None, True, 3, 0.5)
    assert context.known_facts[0].value["segments"] == ("small businesses",)
    for value, name in ((invocation, "objective"), (saved, "producer_node_id"), (predecessor, "schema_version")):
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, "changed")
    with pytest.raises(TypeError):
        predecessor.payload["scenes"][0]["text"] = "changed"
    with pytest.raises(AttributeError):
        predecessor.payload["scenes"].append("changed")


def test_normalized_quality_contract_is_reused_including_immutable_claims():
    parents = ["clm_parent"]
    claim = NormalizedClaim("clm_test", "headline", ClaimType.HYPOTHESIS, Confidence.LOW,
                            AuthorityStatus.WITHIN_SCOPE, "offer", ClaimLineageType.DERIVES,
                            parent_claim_ids=parents)
    claims = [claim]
    quality = normalized(claims=claims)
    output = result(normalized_result=quality)
    parents.clear()
    claims.clear()
    assert output.normalized_result is quality
    assert quality.claims[0].parent_claim_ids == ("clm_parent",)
    with pytest.raises(FrozenInstanceError):
        quality.claims[0].value = "changed"


class StringSubclass(str):
    pass


class HostileMapping(Mapping):
    def __getitem__(self, key): raise AssertionError("must not access custom mappings")
    def __iter__(self): raise AssertionError("must not iterate custom mappings")
    def __len__(self): raise AssertionError("must not measure custom mappings")


class HostileList(list):
    def __iter__(self): raise AssertionError("must not iterate custom containers")


@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), float("-inf"), Decimal("1.5"), b"bytes", bytearray(b"bytes"),
    {1: "integer key"}, {StringSubclass("key"): "subclass key"}, {"set"}, frozenset({"set"}),
    object(), StringSubclass("text"), ModuleId.CREATOR, HostileMapping(), HostileList([1]),
    MappingProxyType({}), MappingProxyType(HostileMapping()),
])
def test_payload_rejects_unknown_coercive_and_mutable_non_json_types(value):
    with pytest.raises(ModuleExecutionContractError):
        result(payload={"nested": [{"value": value}]})


@pytest.mark.parametrize("payload", [[], (), "text", None, MappingProxyType({}), HostileMapping()])
def test_payload_requires_an_exact_json_object(payload):
    with pytest.raises(ModuleExecutionContractError, match="payload"):
        result(payload=payload)


def test_cyclic_payload_fails_closed():
    source = {}
    source["cycle"] = source
    with pytest.raises(ModuleExecutionContractError, match="acyclic"):
        result(payload=source)


@pytest.mark.parametrize("field,value", [
    ("execution_id", 5), ("execution_id", "invalid identity"), ("execution_id", "a" * 129),
    ("module_id", "CREATOR"), ("objective", 7), ("objective", " "),
    ("expected_outputs", "headline"), ("expected_outputs", []), ("expected_outputs", ["headline", "headline"]),
    ("expected_outputs", [False]), ("expected_outputs", HostileList(["headline"])),
    ("context_packet", {}), ("upstream_results", {}), ("upstream_results", [result()]),
])
def test_request_fails_closed_on_invalid_fields(field, value):
    with pytest.raises(ModuleExecutionContractError):
        request(**{field: value})


@pytest.mark.parametrize("field,value", [
    ("module_id", "CREATOR"), ("schema_version", True), ("schema_version", ""),
    ("schema_version", "not a version"), ("normalized_result", {}),
])
def test_result_rejects_invalid_envelope_fields(field, value):
    with pytest.raises(ModuleExecutionContractError):
        result(**{field: value})


@pytest.mark.parametrize("field", ["reasoning", "chain_of_thought", "job", "session", "credentials"])
def test_contracts_have_no_hidden_reasoning_or_runtime_ownership_fields(field):
    with pytest.raises(TypeError):
        request(**{field: "not permitted"})
    with pytest.raises(TypeError):
        result(**{field: "not permitted"})
    assert field not in {f.name for f in fields(ModuleExecutionResult)}


def test_result_module_must_match_quality_module():
    with pytest.raises(ModuleCompatibilityError, match="normalized_result.module_id"):
        result(normalized_result=normalized(ModuleId.MENTOR))


@pytest.mark.parametrize("node", ["analysis", "another-node"])
def test_duplicate_upstream_result_identity_is_rejected_even_for_different_producers(node):
    first = UpstreamExecutionResult(producer_node_id="analysis", result=result())
    second = UpstreamExecutionResult(producer_node_id=node, result=result(ModuleId.MENTOR))
    with pytest.raises(ModuleExecutionContractError, match="identities must be unique"):
        request(upstream_results=[first, second])


def test_distinct_results_from_same_producer_are_not_conflated():
    upstream = [UpstreamExecutionResult(producer_node_id="analysis", result=result(normalized_result=normalized(identity=rid)))
                for rid in ("res_one", "res_two")]
    assert request(upstream_results=upstream).upstream_results == tuple(upstream)


@pytest.mark.parametrize("values", [dict(producer_node_id=" ", result=result()), dict(producer_node_id="analysis", result={})])
def test_upstream_envelope_is_strict(values):
    with pytest.raises(ModuleExecutionContractError):
        UpstreamExecutionResult(**values)


@pytest.mark.parametrize("key", ["", " Test.creator", "TEST.creator", "test.creator ", "test..creator", "test/creator", "x" * 129, 7, True, StringSubclass("test.creator")])
def test_executor_keys_are_exact_and_never_normalized(key):
    with pytest.raises(ValueError, match="executor_key"):
        binding(executor_key=key)
    with pytest.raises(ExecutorRegistrationError, match="executor_key"):
        ModuleExecutorRegistry([FakeExecutor(executor_key=key)])
    with pytest.raises(ExecutorRegistrationError, match="executor_key"):
        ModuleExecutorRegistry().resolve(key)


@pytest.mark.parametrize("values", [dict(compatibility="partial"), dict(compatibility=True), dict(evidence=" "),
                                      dict(contract_version=1), dict(contract_version=" "), dict(agent_id="strategy")])
def test_declarative_binding_has_strict_generic_shape(values):
    with pytest.raises((ValueError, TypeError)):
        binding(**values)


def test_binding_is_immutable_and_declares_no_python_agent_target():
    declaration = binding(executor_key="unregistered.executor")
    assert {f.name for f in fields(declaration)} == {"executor_key", "contract_version", "compatibility", "evidence"}
    with pytest.raises(FrozenInstanceError):
        declaration.executor_key = "changed"


def test_lookup_is_exact_does_not_execute_and_registry_copies_registrations():
    fake = FakeExecutor()
    registrations = [fake]
    registry = ModuleExecutorRegistry(registrations)
    registrations.clear()
    assert registry.resolve("test.creator.v1") is fake
    fake.execute.assert_not_called()
    for key in ("creator", "test.creator-v1", "test.creator.v2"):
        with pytest.raises(UnknownExecutorError):
            registry.resolve(key)
    with pytest.raises(UnknownExecutorError):
        ModuleExecutorRegistry().resolve(fake.executor_key)


def test_duplicate_registration_fails_before_any_execution():
    first, second = FakeExecutor(), FakeExecutor()
    with pytest.raises(DuplicateExecutorError):
        ModuleExecutorRegistry([first, second])
    first.execute.assert_not_called()
    second.execute.assert_not_called()


@pytest.mark.parametrize("overrides", [dict(module_id="CREATOR"), dict(contract_version=True), dict(contract_version=""), dict(execute=lambda request: result())])
def test_registry_validates_metadata_and_async_operation(overrides):
    with pytest.raises(ExecutorRegistrationError):
        ModuleExecutorRegistry([FakeExecutor(**overrides)])


@pytest.mark.parametrize("name,value", [("executor_key", "changed.key"), ("module_id", ModuleId.MENTOR), ("contract_version", "module_executor.v2")])
def test_registered_metadata_must_stay_stable(name, value):
    fake = FakeExecutor()
    registry = ModuleExecutorRegistry([fake])
    setattr(fake, name, value)
    with pytest.raises(ExecutorRegistrationError, match="metadata changed"):
        registry.resolve("test.creator.v1")
    fake.execute.assert_not_called()


def test_dispatch_invokes_exact_executor_once_and_does_not_evaluate_quality_again(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("must not evaluate quality")
    monkeypatch.setattr(QualityGateEvaluator, "evaluate", forbidden)
    fake, invocation = FakeExecutor(), request()
    actual = dispatch(fake, invocation=invocation)
    assert actual is fake.execute.return_value
    fake.execute.assert_awaited_once_with(invocation)


def test_dispatch_unknown_key_fails_before_execution():
    fake = FakeExecutor()
    with pytest.raises(UnknownExecutorError):
        dispatch(fake, declaration=binding(executor_key="test.missing"))
    fake.execute.assert_not_called()


@pytest.mark.parametrize("binding_version,executor_version", [
    ("module_executor.v2", MODULE_EXECUTION_CONTRACT_VERSION),
    (MODULE_EXECUTION_CONTRACT_VERSION, "module_executor.v2"),
    ("module_executor.v2", "module_executor.v2"),
])
def test_dispatch_only_supports_the_closed_v1_contract(binding_version, executor_version):
    fake = FakeExecutor(contract_version=executor_version)
    with pytest.raises(ContractVersionError):
        dispatch(fake, declaration=binding(contract_version=binding_version))
    fake.execute.assert_not_called()


def test_request_must_match_executor_exact_module():
    fake = FakeExecutor(module_id=ModuleId.MENTOR)
    with pytest.raises(ModuleCompatibilityError, match="executor.module_id"):
        dispatch(fake)
    fake.execute.assert_not_called()


def test_executor_cannot_return_another_modules_result():
    fake = FakeExecutor(execute=AsyncMock(return_value=result(ModuleId.MENTOR)))
    with pytest.raises(ModuleCompatibilityError, match="returned result"):
        dispatch(fake)
    fake.execute.assert_awaited_once()


@pytest.mark.parametrize("invalid", [None, {}, normalized(), "result"])
def test_executor_must_return_the_typed_execution_result(invalid):
    fake = FakeExecutor(execute=AsyncMock(return_value=invalid))
    with pytest.raises(ModuleExecutionContractError, match="must return ModuleExecutionResult"):
        dispatch(fake)
    fake.execute.assert_awaited_once()


@pytest.mark.parametrize("failure", [RuntimeError("provider failed"), ValueError("provider rejected"), asyncio.CancelledError()])
def test_dispatch_propagates_original_exception_or_cancellation_without_retry(failure):
    fake = FakeExecutor(execute=AsyncMock(side_effect=failure))
    with pytest.raises(type(failure)) as caught:
        dispatch(fake)
    assert caught.value is failure
    fake.execute.assert_awaited_once()


def test_dispatch_rejects_untyped_inputs_before_lookup():
    fake = FakeExecutor()
    for values in (dict(declaration={}), dict(invocation={})):
        with pytest.raises(ModuleExecutionContractError):
            dispatch(fake, **values)
    fake.execute.assert_not_called()


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and not node.level] + [
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]


def test_architecture_separates_metadata_from_implementations_and_forbids_reverse_dependencies():
    assert ModuleRegistry is not ModuleExecutorRegistry
    for path in (ROOT / "app/module_registry").glob("*.py"):
        assert not [name for name in _imports(path) if name.startswith("app.") and not name.startswith("app.module_registry")]
    allowed = ("app.module_registry", "app.marketing_orchestrator.contracts", "app.marketing_orchestrator.errors",
               "app.marketing_orchestrator.quality_gates.contracts")
    for path in (ROOT / "app/module_execution").glob("*.py"):
        assert not [name for name in _imports(path) if name.startswith("app.") and not name.startswith(allowed)]
    # Only explicit internal graph/application boundaries may consume execution.
    for directory in (ROOT / "app", ROOT / "bot"):
        for path in directory.rglob("*.py"):
            if not {"module_execution", "orchestration_runtime"}.intersection(path.parts) and path not in {
                ROOT / "app/marketing_copilot/application_contracts.py", ROOT / "app/marketing_copilot/factory.py",
                ROOT / "app/marketing_copilot/service.py",
            }:
                assert "module_execution" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize("order", tuple(permutations((
    "app.module_registry", "app.module_execution", "app.marketing_orchestrator", "app.marketing_orchestrator.quality_gates",
))))
def test_fresh_import_orders_have_no_cycles_or_legacy_runtime_imports(order):
    script = """
import importlib, sys
for name in sys.argv[1:]:
    importlib.import_module(name)
from app.module_registry import ModuleRegistry
assert len(ModuleRegistry.load().descriptors) == 15
forbidden = ('app.services', 'app.agents', 'app.workflows', 'app.routers', 'app.db', 'bot', 'sqlalchemy', 'redis', 'openai', 'aiogram')
assert not [m for m in sys.modules if any(m == p or m.startswith(p + '.') for p in forbidden)]
"""
    completed = subprocess.run([sys.executable, "-c", script, *order], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("agent_type", ["strategy", "content", "analytics", "promo", "trends"])
def test_legacy_agent_runner_keeps_input_overrides_and_output_behavior(monkeypatch, agent_type):
    from app.services.agent_registry import AgentRegistry
    from app.services.agent_runner import AgentRunner

    calls = []
    class FakeLegacyAgent:
        async def run(self, brief, **kwargs):
            calls.append((brief, kwargs, self.model_override, self.max_output_tokens_override))
            return {"user_answer": "  Legacy response  ", "assumptions": ["assumption"], "confidence": "low", "warnings": ["warning"]}

    monkeypatch.setitem(AgentRegistry._AGENT_MAP, agent_type, FakeLegacyAgent)
    actual = asyncio.run(AgentRunner().run(agent_type, "Prepare marketing", {"days": "7"}, "fake-model", 777, ["fix"]))
    assert calls == [({"task_description": "Prepare marketing", "days": "7", "qc_issues": ["fix"]},
                      {"days": 7} if agent_type == "content" else {}, "fake-model", 777)]
    assert actual == {"content": "Legacy response", "format": "markdown", "assumptions": ["assumption"], "confidence": "low", "warnings": ["warning"]}
    with pytest.raises(ValueError, match="Unknown agent type"):
        asyncio.run(AgentRunner().run("unregistered", "task", {}, "fake", 1))
