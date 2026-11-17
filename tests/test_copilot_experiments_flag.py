"""AI Core 1.0 release gate: COPILOT_EXPERIMENTS_ENABLED=false plans strategies without EXPERIMENTS.

The flag only changes planning of new runs. A disabled plan records the explicit
limitation experiments_disabled, never calls the EXPERIMENTS executor and shows the
user a temporary-limitation notice. Graphs already started keep their persisted plan.
"""
import asyncio
from dataclasses import replace
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.config import Settings, settings
from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_resolver import ContextEntry
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.marketing_copilot.run_reader import GraphRunReader
from app.marketing_orchestrator import MarketingOrchestratorPlanner, RequestInterpretation
from app.marketing_orchestrator.strategy import EXPERIMENTS_DISABLED, strategy_topology
from app.models import JobStatus, User
from app.module_registry import ModuleId, ModuleRegistry
from app.orchestration_runtime.compiler import PlanCompiler
from app.orchestration_runtime.serialization import plan_from_json, plan_to_json
from app.orchestration_runtime.service import GraphExecutionService
from bot import copilot_contracts as bot_dto, copilot_rendering as render
from tests.postgresql_support import mvp_database  # noqa: F401  (fixture)
from tests.test_copilot_application import intent_model
from tests.test_graph_postgresql import Clock, cleanup, state
from tests.test_strategy_builder import SCENARIO, StrategyModel, strategy_context, strategy_executors
from tests.test_strategy_builder_postgresql import drain

NOTICE = "Experiments are temporarily disabled."


def plan(enabled, context=None):
    return MarketingOrchestratorPlanner(experiments_enabled=enabled).plan(RequestInterpretation(
        requested_output="strategy", decision_goal="Grow qualified demand", business_goal="UNSPECIFIED",
        intent="MARKETING_STRATEGY", object="product", depth="bounded", mode="PLANNING_ONLY", scenario_key=SCENARIO),
        context if context is not None else strategy_context())


def compile_plan(source):
    return PlanCompiler(ModuleRegistry.load("1.3.0"), strategy_executors()).compile(source)


def test_flag_defaults_to_enabled_and_release_configuration_can_disable_it(monkeypatch):
    assert Settings.model_fields["COPILOT_EXPERIMENTS_ENABLED"].default is True
    monkeypatch.setenv("COPILOT_EXPERIMENTS_ENABLED", "false")
    assert Settings().COPILOT_EXPERIMENTS_ENABLED is False


@pytest.mark.parametrize("competitors,market", [(0, False), (2, True)])
def test_disabled_plan_has_no_experiments_node_and_records_the_limitation(competitors, market):
    context = strategy_context(tuple(f"https://competitor{i}.example/" for i in range(competitors)), market)
    enabled, disabled = plan(True, context), plan(False, context)
    assert [n.node_id for n in enabled.nodes][-1] == "experiments"
    assert EXPERIMENTS_DISABLED not in enabled.limitations
    assert [n.node_id for n in disabled.nodes] == [n.node_id for n in enabled.nodes][:-1]
    assert all(n.module_id is not ModuleId.EXPERIMENTS for n in disabled.nodes)
    assert ("virtual_cmo", "experiments") not in {(e.upstream_node_id, e.downstream_node_id) for e in disabled.dependencies}
    assert disabled.limitations == (*enabled.limitations, EXPERIMENTS_DISABLED)
    compiled = compile_plan(disabled)
    assert [n.node_id for n in compiled.nodes][-2:] == ["positioning", "virtual_cmo"]
    assert compiled.limitations[-1] == EXPERIMENTS_DISABLED
    assert plan_from_json(plan_to_json(compiled)) == compiled
    # Same economics limitation logic as the enabled plan: it reads the CMO node, not the last node.
    assert ("economics_unavailable" in disabled.limitations) == ("economics_unavailable" in enabled.limitations)


def test_absent_experiments_must_be_explicit_and_disabled_experiments_must_be_absent():
    enabled, disabled = plan(True), plan(False)
    with pytest.raises(ValueError):  # hidden omission: no node and no explicit limitation
        strategy_topology(disabled.nodes, disabled.dependencies, ())
    with pytest.raises(ValueError):  # contradiction: limitation recorded but node still planned
        strategy_topology(enabled.nodes, enabled.dependencies, (EXPERIMENTS_DISABLED,))
    strategy_topology(enabled.nodes, enabled.dependencies, enabled.limitations)
    strategy_topology(disabled.nodes, disabled.dependencies, disabled.limitations)
    for source in (replace(disabled, limitations=disabled.limitations[:-1]),
                   replace(enabled, limitations=(*enabled.limitations, EXPERIMENTS_DISABLED))):
        with pytest.raises(Exception):
            compile_plan(source)


def test_production_api_passes_the_release_flag(monkeypatch):
    from app.marketing_copilot import production
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("captured")

    graph = type("Graph", (), {"executors": object(), "service": object(),
                               "metadata": type("M", (), {"version": "1.3.0"})()})()
    monkeypatch.setattr(production, "build_production_graph_runtime", lambda **kwargs: graph)
    monkeypatch.setattr(production, "build_marketing_copilot_service", capture)
    for value in (False, True):
        monkeypatch.setattr(settings, "COPILOT_EXPERIMENTS_ENABLED", value)
        with pytest.raises(RuntimeError, match="captured"):
            production.build_production_copilot_api(queue=object(), sessions=object())
        assert seen["experiments_enabled"] is value


def test_notice_is_rendered_in_russian_without_hiding_the_strategy():
    from app.marketing_copilot.presentation import COVERAGE_MESSAGES
    assert COVERAGE_MESSAGES[EXPERIMENTS_DISABLED] == NOTICE
    strategy = bot_dto.Strategy(**{key: bot_dto.StrategySection(text="Текст", items=["Действие"]) for key in render.SECTIONS})
    result = bot_dto.RunResponse(run_id="a" * 64, status=bot_dto.RunStatus.COMPLETED, strategy=strategy,
        evidence_coverage=bot_dto.Coverage(competitors_supplied=0, competitors_accepted=0, limitations=[NOTICE]))
    text = "\n".join(render.run(result))
    assert all(title in text for title in render.SECTIONS.values())
    assert "План экспериментов временно не формируется" in text and NOTICE not in text


async def start(db, *, enabled, model, executors, service):
    async with db() as session, session.begin():
        user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
        session.add(user)
        await session.flush()
        owner, telegram_id = user.id, user.telegram_id
    context = strategy_context()
    copilot = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY),
        executor_registry=executors, graph_service=service, registry_version="1.3.0", experiments_enabled=enabled)
    request = CopilotRequest(actor_id=owner, request_id=uuid.uuid4().hex, message="Build a strategy",
        current_request=tuple(ContextEntry(f.input_key.value if f.input_key else f.label, f) for f in context.known_facts),
        available_tools=context.available_tools)
    response = await copilot.execute(request)
    assert response.kind is ResultKind.WORKFLOW_STARTED and not model.calls
    return response.workflow.run_id, owner, telegram_id


def experiments_calls(model):
    return [c for c in model.calls if "experiments_support_selection_catalog" in c["text"]
            or "experiments" in json.loads(c["text"]).get("expected_outputs", [])
            or "evidence_basis" in json.loads(c["text"]).get("expected_outputs", [])]


def graph(db):
    model = StrategyModel(use_parents=True)
    executors = strategy_executors(model)
    queue = type("DownQueue", (), {"wake": AsyncMock(side_effect=ConnectionError("offline"))})()
    return model, executors, GraphExecutionService(db, executors=executors, clock=Clock(), queue=queue)


def test_disabled_graph_never_calls_experiments_and_reports_the_limitation(mvp_database):
    async def exercise():
        model, executors, service = graph(mvp_database)
        rid, owner, telegram_id = await start(mvp_database, enabled=False, model=model, executors=executors, service=service)
        try:
            await drain(service, mvp_database, rid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed" and run.error is None
            assert sorted(j.workflow_step for j in jobs) == ["positioning", "virtual_cmo"]
            assert all(j.status is JobStatus.SUCCEEDED for j in jobs)
            assert {a.step for a in artifacts} == {"positioning", "virtual_cmo"}
            assert {"code": EXPERIMENTS_DISABLED} in run.state_json["limitations"]
            assert model.calls and not experiments_calls(model)
            projection = await GraphRunReader(mvp_database, service).get(telegram_id, rid)
            assert projection.strategy is not None and projection.experiments is None
            assert NOTICE in projection.evidence_coverage.limitations
            calls = len(model.calls)
            await GraphRunReader(mvp_database, service).get(telegram_id, rid)
            assert len(model.calls) == calls  # reading never generates
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_graph_started_before_the_flag_change_keeps_its_experiments(mvp_database):
    async def exercise():
        model, executors, service = graph(mvp_database)
        rid, owner, _ = await start(mvp_database, enabled=True, model=model, executors=executors, service=service)
        try:
            # A later process plans with the flag off; the persisted plan of this run is unchanged.
            later = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY),
                executor_registry=executors, graph_service=service, registry_version="1.3.0", experiments_enabled=False)
            assert later.planner is not None
            await drain(service, mvp_database, rid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed"
            assert sorted(j.workflow_step for j in jobs) == ["experiments", "positioning", "virtual_cmo"]
            assert {a.step for a in artifacts} == {"positioning", "virtual_cmo", "experiments"}
            assert {"code": EXPERIMENTS_DISABLED} not in run.state_json["limitations"]
            assert experiments_calls(model)
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
