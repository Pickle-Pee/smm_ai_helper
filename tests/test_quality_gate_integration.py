import hashlib,json
from importlib.resources import files
from pathlib import Path
from app.module_registry import ModuleRegistry
from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import batch

EXPECTED="25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918"
def test_registry_identity_checksum_and_planning_only_integration():
    registry=ModuleRegistry.load();raw=json.loads(files("app.module_registry").joinpath("v1.0.0.json").read_text(encoding="utf-8"));normalized=json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    assert registry.version=="1.0.0";assert len(registry.descriptors)==15;assert not any(x.execution_binding for x in registry.descriptors);assert hashlib.sha256(normalized).hexdigest()==EXPECTED
    assert QualityGateEvaluator(registry).evaluate(batch()).execution_readiness is ExecutionReadiness.PLANNING_ONLY
def test_package_is_architecturally_isolated_by_import_boundary():
    root=Path(__file__).parents[1]/"app/marketing_orchestrator/quality_gates"
    text="\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    forbidden=("app.llm","QCService","TaskPipelineService","sqlalchemy","redis","app.routers","bot.","app.agents","app.presenters","MarketingOrchestrator")
    assert not any(token in text for token in forbidden)
def test_existing_execution_paths_do_not_import_quality_gates():
    root=Path(__file__).parents[1]
    paths=[*root.glob("app/**/*.py"),*root.glob("bot/**/*.py")]
    assert not any("quality_gates" in p.read_text(encoding="utf-8") for p in paths if "quality_gates" not in p.parts)
def test_internal_exports_are_closed():
    import app.marketing_orchestrator.quality_gates as q
    assert "Any" not in q.__all__;assert "dataclass" not in q.__all__;assert "QualityGateEvaluator" in q.__all__

def test_external_and_execution_call_count_is_exactly_zero(monkeypatch):
    calls={"llm":0,"qc":0,"pipeline":0,"persistence":0}
    def forbidden(name):
        def fail(*_a,**_k):calls[name]+=1;raise AssertionError(name)
        return fail
    monkeypatch.setattr("app.llm.openai_text.chat",forbidden("llm"))
    monkeypatch.setattr("app.services.qc_service.QCService.find_issues",forbidden("qc"))
    monkeypatch.setattr("app.services.task_pipeline.TaskPipelineService.start_task",forbidden("pipeline"))
    monkeypatch.setattr("app.services.marketing_workflow_persistence_service.MarketingWorkflowPersistenceService.update_run",forbidden("persistence"))
    QualityGateEvaluator().evaluate(batch())
    assert calls=={"llm":0,"qc":0,"pipeline":0,"persistence":0}
