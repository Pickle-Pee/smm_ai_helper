"""Owned context survives real graph persistence and gates; external providers faked."""
import asyncio
from dataclasses import replace
import json
import uuid

import pytest
from sqlalchemy import select

from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.models import MarketingRun, OrchestrationPlanRecord, User
from app.module_registry import ToolCapability
from app.orchestration_runtime.serialization import plan_from_json
from app.orchestration_runtime.service import GraphExecutionService
from app.product_context import ConfirmedBusinessFact, TrustKind
from app.product_context.projection import attach_acquisition, project_confirmation
from tests.postgresql_support import mvp_database
from tests.test_copilot_application import intent_model
from tests.test_graph_postgresql import cleanup, state
from tests.test_product_context import acquisition, entry, OWN, COMPETITOR
from tests.test_strategy_builder import strategy_executors, StrategyModel
from tests.test_strategy_builder_postgresql import drain


@pytest.mark.parametrize("kind", [IntentKind.MARKETING_STRATEGY, IntentKind.COMPARATIVE_POSITIONING])
def test_owned_context_confirmation_persistence_execution_and_source_isolation(mvp_database, kind):
    acquired, _, _ = acquisition()
    async def exercise():
        model = StrategyModel(use_parents=True)
        executors = strategy_executors(model)
        graph = GraphExecutionService(mvp_database, executors=executors)
        async with mvp_database() as session, session.begin():
            user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(user)
            await session.flush()
            owner = user.id
        svc = build_marketing_copilot_service(intent_model=intent_model(kind, (OWN, COMPETITOR)),
            executor_registry=executors, graph_service=graph, registry_version="1.2.0")
        source_key = "competitor_urls" if kind is IntentKind.MARKETING_STRATEGY else "competitor_url"
        req = attach_acquisition(CopilotRequest(actor_id=owner, request_id=uuid.uuid4().hex,
            message=f"Build strategy using our site {OWN} and competitor {COMPETITOR}",
            current_request=(entry("business_goal", "Increase appointments"),
                entry("relevant_alternative", "Manual scheduling"),
                entry(source_key, [COMPETITOR] if source_key == "competitor_urls" else COMPETITOR)),
            available_tools=frozenset({ToolCapability.SITE_FETCH})), acquired)
        rid = "no-run"
        try:
            result = await svc.execute(req)
            assert result.kind is ResultKind.NEEDS_INPUT
            assert result.clarification.alternatives == (("product_truth",),)
            async with mvp_database() as session:
                assert not (await session.scalars(select(MarketingRun).where(MarketingRun.user_id == owner))).all()
            confirmation = ConfirmedBusinessFact(snapshot_id=acquired.snapshot.snapshot_id,
                statement_ids=(acquired.snapshot.statements[0].statement_id,),
                confirmed_by="owner", confirmation_reference="explicit-caller-confirmation")
            req = replace(req, current_request=(*req.current_request, project_confirmation(acquired.snapshot, confirmation)))
            result = await svc.execute(req)
            assert result.kind is ResultKind.WORKFLOW_STARTED
            rid = result.workflow.run_id
            async with mvp_database() as session:
                record = await session.get(OrchestrationPlanRecord, (rid, 1))
                plan = plan_from_json(record.compiled_plan_json)
                for node in plan.nodes:
                    for f in (*node.context_packet.known_facts, *node.context_packet.relevant_project_context):
                        if f.label == "product":
                            assert f.value["trust"] == "site_claim"
                            assert f.evidence == tuple(e["record"]["evidence_id"] for e in f.value["evidence"])
            # Recreate application runtime from persistence before actual execution.
            restarted = GraphExecutionService(mvp_database, executors=executors)
            await drain(restarted, mvp_database, rid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed", [(j.workflow_step, j.error) for j in jobs]
            assert artifacts and model.calls
            data = [json.loads(call["text"]) for call in model.calls]
            external = [e for call in data for e in call["local_evidence"] if e["source_class"] == "EXTERNAL_PRIMARY"]
            assert external and all(OWN not in e["provenance"] for e in external)
            assert acquired.snapshot.trust is TrustKind.SITE_CLAIM
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
