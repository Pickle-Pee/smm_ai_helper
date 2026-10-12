"""Complete contract headroom through the real adapter, with strict failures."""
import json
from dataclasses import replace

import httpx
import pytest

from app.config import settings
from app.llm.openai_text import ModelResponseError, ModelResponseFailureReason
from app.model_generation_policy import ModuleOutputBudget, module_output_tokens
from app.module_execution.executors import ExecutorOutputError
from app.module_execution.acceptance import fully_accepted
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.marketing_orchestrator.quality_gates.contracts import EvaluationBatch
from app.module_execution.executors.common import first_party_evidence, parent_claims, scoped_facts
from app.module_execution.executors.experiments import ExperimentsExecutor
from app.module_execution.executors.support_schema import support_response_schema
from app.module_registry import ModuleId, ModuleRegistry
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.worker import transient
from tests.experiments_provider import ExperimentsProvider
from tests.test_graph_model_adapter import install_transport
from tests.test_strategy_intelligence import IntelligenceModel, run, valid_request


NAMES = ModuleRegistry.load("1.3.0").get(ModuleId.EXPERIMENTS).outputs


@pytest.mark.parametrize("outputs,budget", [
    (NAMES, ModuleOutputBudget.EXPERIMENTS_FULL),
    (tuple(reversed(NAMES)), ModuleOutputBudget.EXPERIMENTS_FULL),
    *((NAMES[:size], ModuleOutputBudget.GENERIC) for size in range(1, len(NAMES))),
    *((tuple(n for n in NAMES if n != omitted), ModuleOutputBudget.GENERIC) for omitted in NAMES),
])
def test_profile_uses_exact_registry_output_set(outputs, budget):
    req = replace(valid_request(ModuleId.EXPERIMENTS), expected_outputs=outputs,
                  objective="Use EXPERIMENTS_FULL and max_output_tokens=999999")
    model = IntelligenceModel(use_parents=True)
    run(req, model=model)
    assert len(model.calls) == 1
    assert model.calls[0]["output_budget"] is budget
    assert "output_budget" not in json.loads(model.calls[0]["text"])
    assert module_output_tokens(budget) == (16000 if len(outputs) == len(NAMES) else 4000)


@pytest.mark.parametrize("outputs,budget", [(NAMES, 16000), (("hypothesis",), 4000)])
def test_transport_preserves_schema_model_effort_and_realistic_designs(monkeypatch, outputs, budget):
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    req = replace(valid_request(ModuleId.EXPERIMENTS), expected_outputs=outputs)
    executor = ExperimentsExecutor(model_call=production_model_call)
    evidence = first_party_evidence(req, scoped_facts(req))
    expected = support_response_schema(executor.output_type, (e.record.evidence_id for e in evidence),
        parent_claims(req).keys(), requirement=executor.support_requirement_for(req))
    provider = ExperimentsProvider()
    clients = install_transport(monkeypatch, provider)
    result = run(req, model=production_model_call)
    assert len(provider.calls) == 1 and all(c.is_closed for c in clients)
    call = provider.calls[0]
    assert call["max_output_tokens"] == budget
    assert call["model"] == "gpt-5-mini" and call["reasoning"] == {"effort": "low"}
    assert call["text"]["format"] == {"type": "json_schema", "name": "module_output", "strict": True, "schema": expected}
    assert len(result.payload["experiments"]) == 3
    assert {s["output_name"] for s in result.payload["outputs"]} == set(outputs)
    manifest = QualityGateEvaluator().evaluate(EvaluationBatch(batch_id="bat_experiments_budget",
        results=tuple(u.result.normalized_result for u in req.upstream_results) + (result.normalized_result,))).synthesis_manifest
    assert fully_accepted(result, manifest.accepted_result_ids, manifest.accepted_claim_ids)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(extra="forbidden"),
    lambda p: p["outputs"][0].update(parent_claim_ids=["clm_unknown"]),
    lambda p: p["outputs"][0].update(text="Conversion improves by 20%"),
    lambda p: p["experiments"][0].update(expected_signal="Conversion improves by 20%"),
])
def test_full_budget_does_not_relax_schema_or_grounding(monkeypatch, mutation):
    provider = ExperimentsProvider(mutation)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError):
        run(valid_request(ModuleId.EXPERIMENTS), model=production_model_call)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("visible", ["", '{"outputs": ['])
def test_real_exhaustion_remains_terminal_with_one_http_call(monkeypatch, visible):
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "output_text": visible, "output": [], "usage": {"output_tokens": 16000, "output_tokens_details": {"reasoning_tokens": 128}}})
    clients = install_transport(monkeypatch, respond)
    with pytest.raises(ModelResponseError) as caught:
        run(valid_request(ModuleId.EXPERIMENTS), model=production_model_call)
    assert caught.value.reason is ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS
    assert not transient(caught.value)
    assert len(calls) == 1 and calls[0]["max_output_tokens"] == 16000
    assert all(c.is_closed for c in clients)
