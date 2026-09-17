"""First unified application -> durable worker vertical, real SQL and fake providers."""
import asyncio
from dataclasses import replace
import uuid
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_resolver import ContextEntry
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.marketing_copilot.service import identity
from app.marketing_orchestrator.contracts import PlanningInputKey
from app.models import Job, JobExecution, MarketingArtifact, MarketingRun, User
from app.module_execution import ModuleExecutorDispatcher
from app.module_registry import ModuleId, ToolCapability
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.errors import StartIdentityConflict, RuntimeContractError
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from app.orchestration_runtime.serialization import fingerprint
from tests.test_copilot_application import entries, intent_model
from tests.graph_fakes import registry, source_plan, FakeModel
from tests.postgresql_support import mvp_database
from tests.test_graph_postgresql import cleanup, state, setup


def workflow_entries():
    facts = source_plan().nodes[0].context_packet.known_facts
    return tuple(ContextEntry(f.input_key.value, f) for f in facts
                 if f.input_key is not PlanningInputKey.OBSERVABLE_EVIDENCE)


def test_unified_workflow_start_replay_conflict_and_explicit_worker_completion(mvp_database):
    async def exercise():
        model = FakeModel(use_parents=True)
        executors = registry(model)
        graph = GraphExecutionService(mvp_database, executors=executors)
        svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.COMPARATIVE_POSITIONING),
                                              executor_registry=executors, graph_service=graph)
        async with mvp_database() as session, session.begin():
            user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(user)
            await session.flush()
            owner = user.id
        req = CopilotRequest(actor_id=owner, request_id=uuid.uuid4().hex,
            message="Вот наш продукт и конкурент. Найди отличия и предложи позиционирование.",
            current_request=workflow_entries(), available_tools=frozenset({ToolCapability.SITE_FETCH}))
        rid = identity("copilot.run.v1", owner, req.request_id)
        try:
            svc.dispatcher.dispatch = AsyncMock(side_effect=AssertionError("application cannot execute workflow nodes"))
            started = await svc.execute(req)
            assert started.kind is ResultKind.WORKFLOW_STARTED
            assert started.workflow.run_id == rid and not model.calls
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "queued" and len(jobs) == 1 and not artifacts
            assert jobs[0].workflow_step == "competitor_analysis"
            assert (await svc.execute(req)).workflow == started.workflow
            changed = replace(req, current_request=tuple(ContextEntry(e.semantic_key,
                replace(e.fact, value="another product") if e.semantic_key == "product" else e.fact)
                for e in req.current_request))
            with pytest.raises(StartIdentityConflict):
                await svc.execute(changed)
            assert not model.calls
            worker = ModuleGraphWorker(graph)
            assert await worker.once(module_job_id(rid, 1, "competitor_analysis"))
            assert await worker.once(module_job_id(rid, 1, "positioning"))
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed" and len(jobs) == len(artifacts) == 2
            assert {a.payload_json["module_id"] for a in artifacts} == {"COMPETITOR_ANALYSIS", "POSITIONING"}
            assert len(model.calls) == 2
            assert (await svc.execute(req)).workflow == started.workflow
            assert len(model.calls) == 2
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_sync_paths_create_no_graph_entities(mvp_database):
    async def exercise():
        async def counts():
            async with mvp_database() as session:
                return tuple([await session.scalar(select(func.count()).select_from(table))
                              for table in (MarketingRun, Job, JobExecution)])
        before = await counts()
        model = FakeModel()
        svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.POST_GENERATION), module_model=model)
        req = CopilotRequest(actor_id=1, request_id="no-db", message="Напиши пост...", current_request=entries(ModuleId.CREATOR))
        assert (await svc.execute(req)).kind is ResultKind.MODULE_RESULT
        svc.interpreter._model_call = intent_model(IntentKind.LEAD_FUNNEL_CALCULATION)
        assert (await svc.execute(replace(req, message="Рассчитай лиды при бюджете 100000, CPC 50 и конверсии 5%"))).kind is ResultKind.DIRECT_RESULT
        assert await counts() == before
    asyncio.run(exercise())


def test_graph_partial_acceptance_blocks_finish_and_downstream(mvp_database, monkeypatch):
    async def exercise():
        graph, _, rid, owner = await setup(mvp_database)
        original = evaluate_result
        def partial(*args):
            quality = original(*args)
            quality["accepted_claim_ids"] = quality["accepted_claim_ids"][1:]
            return quality
        try:
            item = await graph.claim(module_job_id(rid, 1, "competitor_analysis"))
            binding, req = await graph.load_work(item)
            output = await ModuleExecutorDispatcher(graph.executors).dispatch(binding, req)
            monkeypatch.setattr("app.orchestration_runtime.service.evaluate_result", partial)
            with pytest.raises(RuntimeContractError, match="not accepted"):
                await graph.finish(item, output, partial(item.job_id, output, ()))
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == 1 and not artifacts
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_worker_partial_acceptance_is_quality_rejected(mvp_database, monkeypatch):
    async def exercise():
        graph, _, rid, owner = await setup(mvp_database)
        def partial(*args):
            quality = evaluate_result(*args)
            quality["accepted_claim_ids"] = quality["accepted_claim_ids"][1:]
            return quality
        monkeypatch.setattr("app.orchestration_runtime.worker.evaluate_result", partial)
        try:
            assert await ModuleGraphWorker(graph).once(module_job_id(rid, 1, "competitor_analysis"))
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "failed" and run.error == "quality_rejected"
            assert len(jobs) == 1 and not artifacts
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_reloaded_partial_artifact_never_reaches_downstream(mvp_database, monkeypatch):
    async def exercise():
        model = FakeModel(use_parents=True)
        graph, _, rid, owner = await setup(mvp_database, model)
        try:
            root_id = module_job_id(rid, 1, "competitor_analysis")
            assert await ModuleGraphWorker(graph).once(root_id)
            async with mvp_database() as session, session.begin():
                artifact = await session.scalar(select(MarketingArtifact).where(MarketingArtifact.run_id == rid))
                raw = deepcopy(artifact.payload_json)
                raw["quality"]["accepted_claim_ids"] = raw["quality"]["accepted_claim_ids"][1:]
                artifact.payload_json = raw
                job = await session.get(Job, root_id)
                job.result_json = {**job.result_json, "artifact_fingerprint": fingerprint(raw)}
            def partial(*args):
                quality = evaluate_result(*args)
                quality["accepted_claim_ids"] = quality["accepted_claim_ids"][1:]
                return quality
            # Simulate a persisted partial manifest consistent with reevaluation:
            # checking only equality/result_id would incorrectly release the full payload.
            monkeypatch.setattr("app.orchestration_runtime.service.evaluate_result", partial)
            item = await graph.claim(module_job_id(rid, 1, "positioning"))
            with pytest.raises(RuntimeContractError, match="quality acceptance"):
                await graph.load_work(item)
            assert len(model.calls) == 1
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
