"""Authenticated HTTP to production composition/graph workers, disposable stores."""
import asyncio
import copy
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.config import settings
from app.models import BrandProfile, MarketingRun, OrchestrationPlanRecord, User
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.production import build_production_copilot_api
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.product_context import ExtractorUnavailableError
from app.workflows.queue import RedisWakeups, GRAPH_WAKEUP_KEY
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application, headers, queue
from tests.test_copilot_application import intent_model
from tests.test_module_executors import FakeModel, analyzer
from tests.test_strategy_builder import StrategyModel
from tests.test_graph_postgresql import state
from tests.test_product_context import OWN, PRODUCT, AUDIENCE, JOB, PRICE, LEADER, extraction

CONTEXT = dict(business_goal="Grow bookings", product="Appointment scheduling software",
    target="Small clinics", customer_job_or_need="Reduce scheduling time",
    relevant_alternative="Manual spreadsheets", product_truth="Automated appointment reminders",
    message="Try appointment reminders")


def payload(**overrides):
    return {"request_key": uuid.uuid4().hex, "message": "Build a strategy", "context": dict(CONTEXT), **overrides}


async def remove_actor(db, actor):
    async with db() as session, session.begin():
        owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
        if owner:
            await session.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await session.execute(delete(BrandProfile).where(BrandProfile.user_id == owner))
            await session.execute(delete(User).where(User.id == owner))


def configured(db, kind, **kwargs):
    return build_production_copilot_api(sessions=db, queue=queue(), intent_model=intent_model(kind, kwargs.pop("intent_urls", ())),
        module_model=kwargs.pop("module_model", FakeModel()), analyzer=kwargs.pop("analyzer", analyzer()), **kwargs)


@pytest.mark.parametrize("second_role", ["ignored", "market"])
def test_explicit_competitor_role_overrides_multiple_literal_urls(mvp_database, monkeypatch, second_role):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        urls = ("https://competitor.example", "https://ignored.example")
        site = analyzer()
        site.analyze.return_value.url_summaries[0].update(url=urls[0], final_url=urls[0])
        api = configured(mvp_database, IntentKind.COMPETITOR_ANALYSIS, analyzer=site, intent_urls=urls)
        request = payload(message="Проанализируй " + " ".join(urls), competitor_urls=[urls[0]],
                          market_source_urls=[urls[1]] if second_role == "market" else [])
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=request)
            assert response.status_code == 200, response.text
            public = response.json()
            assert public["kind"] == "MODULE_RESULT", public
            assert public["result"]["kind"] == "competitor_analysis"
            site.analyze.assert_awaited_once_with(urls[0])
            async with mvp_database() as session:
                owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
                assert not (await session.scalars(select(MarketingRun).where(MarketingRun.user_id == owner))).all()
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_comparative_positioning_uses_explicit_competitor_with_multiple_literal_urls(mvp_database, monkeypatch):
    from app.orchestration_runtime.worker import ModuleGraphWorker
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        urls = ("https://competitor.example", "https://market.example", "https://ignored.example")
        site = analyzer()
        site.analyze.return_value.url_summaries[0].update(url=urls[0], final_url=urls[0])
        api = configured(mvp_database, IntentKind.COMPARATIVE_POSITIONING, analyzer=site,
            intent_urls=urls, module_model=FakeModel(use_parents=True))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload(
                    message="Сравни и предложи позиционирование " + " ".join(urls),
                    competitor_urls=[urls[0]], market_source_urls=[urls[1]]))
            assert response.status_code == 202, response.text
            rid = response.json()["run_id"]
            async with mvp_database() as session:
                saved = await session.get(OrchestrationPlanRecord, (rid, 1))
                assert saved.compiled_plan_json["scenario_key"] == "competitive_positioning_v1"
            worker = ModuleGraphWorker(api.copilot.graph_service)
            assert await worker.once()
            assert await worker.once()
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed"
            assert len(jobs) == 2
            assert {a.payload_json["module_id"] for a in artifacts} == {"COMPETITOR_ANALYSIS", "POSITIONING"}
            site.analyze.assert_awaited_once_with(urls[0])
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("kind,expected", [(IntentKind.LEAD_FUNNEL_CALCULATION, "DIRECT_RESULT"),
    (IntentKind.POST_GENERATION, "MODULE_RESULT"), (IntentKind.POSITIONING, "MODULE_RESULT"),
    (IntentKind.COMPETITOR_ANALYSIS, "MODULE_RESULT"), (IntentKind.CONVERSATION, "CONVERSATION")])
def test_sync_http_paths_never_create_run(mvp_database, monkeypatch, kind, expected):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = FakeModel()
        api = configured(mvp_database, kind, module_model=model)
        request = payload(message="Рассчитай лиды при бюджете 100000, CPC 50 и конверсии 5%",
                          competitor_urls=["https://competitor.example/page"])
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert response.status_code == 200, response.text
                public = response.json()
                assert public["kind"] == expected, public
                if expected == "DIRECT_RESULT":
                    assert public["calculation"]["outputs"]["leads"] == "100.00"
                    assert not model.calls
                elif kind is IntentKind.POST_GENERATION:
                    assert public["result"]["body"] == "Use the supplied product to prepare your content."
                elif expected == "CONVERSATION":
                    assert public["delegate"] == "legacy_chat" and not model.calls
                else:
                    assert public["result"]["findings"]
                for forbidden in ("claim_id", "result_id", "executor_key", "normalized_result", "EXPERT_CORE", "fact_id"):
                    assert forbidden not in response.text
            async with mvp_database() as session:
                owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
                assert owner is not None and owner != actor
                assert not (await session.scalars(select(MarketingRun).where(MarketingRun.user_id == owner))).all()
            api.queue.wake.assert_not_awaited()
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_brand_context_and_explicit_empty_precedence(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = FakeModel()
        api = configured(mvp_database, IntentKind.POST_GENERATION, module_model=model)
        async with mvp_database() as session, session.begin():
            user = User(telegram_id=actor)
            session.add(user)
            await session.flush()
            session.add(BrandProfile(user_id=user.id, product_description="Saved product", audience="Saved audience",
                                     extra_json={"message": "Saved message"}))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload(context={}))
                assert response.status_code == 200 and response.json()["kind"] == "MODULE_RESULT", response.text
                assert "Saved product" in model.calls[0]["text"]
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload(context={"product": ""}))
                assert response.json()["kind"] == "NEEDS_INPUT" and len(model.calls) == 1
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("optional_failure", [False, True])
def test_strategy_http_real_stores_fake_transport_worker_and_readonly_polling(mvp_database, monkeypatch, optional_failure):
    if not os.getenv("REDIS_TEST_URL"):
        pytest.skip("REDIS_TEST_URL required")
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "offline-key")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        q = RedisWakeups(Redis.from_url(os.environ["REDIS_TEST_URL"], decode_responses=True), key=GRAPH_WAKEUP_KEY)
        model, site, calls = StrategyModel(use_parents=True), analyzer(), []
        original = httpx.AsyncClient
        async def respond(request):
            value = json.loads(request.content)
            calls.append(value)
            text = value["input"][1]["content"]
            schema = value["text"]["format"]["schema"]
            if "intent" in schema["properties"]:
                output = await intent_model(IntentKind.MARKETING_STRATEGY)()
                assert set(schema["required"]) == set(schema["properties"])
            else:
                data = json.loads(text)
                if optional_failure and "competitor2.example" in json.dumps(data["context"]) and "direct_competitors" in data["expected_outputs"]:
                    return httpx.Response(400, text="private-provider-secret")
                output = await model(instruction=value["input"][0]["content"], text=text, response_schema=schema)
            return httpx.Response(200, json={"status": "completed", "output_text": output})
        def http_client(**kwargs):
            kwargs.setdefault("transport", httpx.MockTransport(respond))
            return original(**kwargs)
        monkeypatch.setattr(httpx, "AsyncClient", http_client)
        api = build_production_copilot_api(sessions=mvp_database, queue=q, analyzer=site)
        runtime = build_production_graph_runtime(sessions=mvp_database, queue=q, analyzer=site)
        request = payload(competitor_urls=["https://competitor1.example/", "https://competitor2.example/"],
                          market_sources=[{"title": "Supplied research", "excerpt": "Clinics report appointment delays."}])
        try:
            await q.client.delete(GRAPH_WAKEUP_KEY)
            async with http_client(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert response.status_code == 202, response.text
                rid = response.json()["run_id"]
                assert not model.calls
                run, jobs, artifacts = await state(mvp_database, rid)
                assert run.user_id != actor and len(jobs) == 3 and artifacts == []
                assert {await q.wait(), await q.wait(), await q.wait()} == {j.job_id for j in jobs}
                async with mvp_database() as session:
                    saved = await session.get(OrchestrationPlanRecord, (rid, 1))
                    assert saved.compiled_plan_json["scenario_key"] == "strategy_builder_v1"
                replay = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert replay.status_code == 202 and replay.json()["run_id"] == rid
                changed = copy.deepcopy(request)
                changed["context"]["product_truth"] = "Different capability"
                conflict = await client.post("/copilot/execute", headers=headers(actor), json=changed)
                assert conflict.status_code == 409 and conflict.json()["code"] == "request_conflict"
                assert len((await state(mvp_database, rid))[1]) == 3
                url = response.json()["status_url"]
                before_calls = len(calls)
                queued = await client.get(url, headers=headers(actor))
                assert queued.status_code == 200 and queued.json()["status"] == "QUEUED", queued.text
                unknown = await client.get("/copilot/runs/" + "f" * 64, headers=headers(actor))
                foreign = await client.get(url, headers=headers(actor + 1))
                assert unknown.status_code == foreign.status_code == 404 and unknown.json() == foreign.json()
                assert len(calls) == before_calls
                # Production worker executes pending durable Jobs; lost hints are harmless.
                await q.client.delete(GRAPH_WAKEUP_KEY)
                for _ in range(10):
                    if (await state(mvp_database, rid))[0].status in {"completed", "completed_with_limitations", "failed", "blocked"}:
                        break
                    assert await runtime.create_worker().once()
                run, jobs, artifacts = await state(mvp_database, rid)
                response = await client.get(url, headers=headers(actor))
                assert response.status_code == 200, response.text
                public = response.json()
                assert public["status"] == ("COMPLETED_WITH_LIMITATIONS" if optional_failure else "COMPLETED"), [(j.workflow_step, j.error) for j in jobs]
                assert len(public["strategy"]) == 10 and public["experiments"]["designs"]
                assert public["evidence_coverage"]["competitors_accepted"] == (1 if optional_failure else 2)
                if optional_failure:
                    assert "One competitor analysis is unavailable." in public["limitations"]
                for forbidden in ("private-provider-secret", "claim_id", "parent_claim_ids", "execution_id", "executor_key", "EXPERT_CORE", "normalized_result"):
                    assert forbidden not in response.text
                before_calls, before_queue = len(calls), await q.client.llen(GRAPH_WAKEUP_KEY)
                replay = await client.get(url, headers=headers(actor))
                assert replay.json() == public and len(calls) == before_calls
                assert await q.client.llen(GRAPH_WAKEUP_KEY) == before_queue
                after, after_jobs, after_artifacts = await state(mvp_database, rid)
                assert after.updated_at == run.updated_at
                assert [(j.status, j.updated_at) for j in after_jobs] == [(j.status, j.updated_at) for j in jobs]
                assert len(after_artifacts) == len(artifacts)
        finally:
            await remove_actor(mvp_database, actor)
            await q.client.delete(GRAPH_WAKEUP_KEY)
            await q.close()
    asyncio.run(check())


def test_owned_confirmation_reacquires_and_rejects_stale_or_unknown_statement(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        page = {"ok": True, "url": OWN, "final_url": OWN, "title": "Acme",
                "main_text_excerpt": "\n".join([PRODUCT, AUDIENCE, JOB, PRICE, LEADER])}
        site = SimpleNamespace(analyze_url=AsyncMock(return_value=SimpleNamespace(url_summaries=[page])))
        extractor = AsyncMock(return_value=extraction())
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, owned_analyzer=site, extractor=extractor)
        request = payload(owned_site_url=OWN, context={"business_goal": "Increase bookings", "relevant_alternative": "Spreadsheets"})
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=request)
                public = response.json()
                assert response.status_code == 200 and public["kind"] == "NEEDS_INPUT", public
                owned = public["owned_site"]
                assert len(owned["candidates"]) == 1
                candidate = owned["candidates"][0]
                assert candidate["statement"] == PRODUCT and candidate["trust"] == "site_claim"
                request["confirmation"] = dict(snapshot_id=owned["snapshot_id"], statement_ids=[candidate["statement_id"]], confirmed=True, reference="I verified this product capability")
                bad = copy.deepcopy(request)
                bad["confirmation"]["statement_ids"] = ["statement.unknown"]
                assert (await client.post("/copilot/execute", headers=headers(actor), json=bad)).status_code == 422
                page["title"] = "Changed page"
                stale = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert stale.status_code == 409 and stale.json()["code"] == "confirmation_changed", stale.text
                page["title"] = "Acme"
                response = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert response.status_code == 202, response.text
                assert site.analyze_url.await_count == extractor.await_count == 4
                run, _, _ = await state(mvp_database, response.json()["run_id"])
                async with mvp_database() as session:
                    saved = await session.get(OrchestrationPlanRecord, (run.run_id, 1))
                    serialized = json.dumps(saved.compiled_plan_json)
                    assert "confirmed_business_fact" in serialized and f"user:{run.user_id}" in serialized
                    def truth_values(value):
                        if isinstance(value, dict):
                            if value.get("input_key") == "product_truth":
                                yield value["value"]
                            for child in value.values():
                                yield from truth_values(child)
                        elif isinstance(value, list):
                            for child in value:
                                yield from truth_values(child)
                    truths = list(truth_values(saved.compiled_plan_json))
                    assert truths and all("We are" not in json.dumps(truth) for truth in truths)
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("failure,expected", [(httpx.ReadTimeout("secret"), 503), (ValueError("bug"), 500)])
def test_http_provider_vs_programming_failure(mvp_database, monkeypatch, failure, expected):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        api = configured(mvp_database, IntentKind.POST_GENERATION, module_model=AsyncMock(side_effect=failure))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api), raise_app_exceptions=False), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload())
                assert response.status_code == expected, response.text
                assert "secret" not in response.text and "bug" not in response.text
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("status,code", [("blocked", "context_required"), ("failed", "result_unavailable"), ("running", None)])
def test_polling_safe_statuses_and_fixed_run_isolation(mvp_database, monkeypatch, status, code):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                started = await client.post("/copilot/execute", headers=headers(actor), json=payload())
                assert started.status_code == 202, started.text
                rid = started.json()["run_id"]
                async with mvp_database() as session, session.begin():
                    run = await session.get(MarketingRun, rid)
                    run.status = status
                    run.error = "SECRET provider response and stack trace"
                    session.add(MarketingRun(run_id="c" * 64, user_id=run.user_id, workflow_type="fixed.workflow.v1", status="queued"))
                public = await client.get(started.json()["status_url"], headers=headers(actor))
                assert public.status_code == 200 and public.json()["status"] == status.upper(), public.text
                assert "SECRET" not in public.text
                if code:
                    assert public.json()["failure"]["code"] == code and public.json()["failure"]["actions"]
                else:
                    assert public.json()["failure"] is None
                assert (await client.get("/copilot/runs/" + "c" * 64, headers=headers(actor))).status_code == 404
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_owned_expected_failure_and_explicit_competitor_role(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        page = {"ok": True, "url": OWN, "final_url": OWN, "main_text_excerpt": PRODUCT}
        owned = SimpleNamespace(analyze_url=AsyncMock(return_value=SimpleNamespace(url_summaries=[page])))
        competitor = analyzer()
        api = configured(mvp_database, IntentKind.COMPETITOR_ANALYSIS, analyzer=competitor, owned_analyzer=owned,
                         extractor=AsyncMock(side_effect=ExtractorUnavailableError("secret")))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload(owned_site_url=OWN, message="Analyze " + OWN))
                assert response.status_code == 200 and response.json()["kind"] == "NEEDS_INPUT", response.text
                assert response.json()["owned_site"]["outcome"] == "CAPABILITY_UNAVAILABLE"
                assert "secret" not in response.text
                competitor.analyze.assert_not_awaited()
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload(
                    owned_site_url=OWN, competitor_urls=["https://competitor.example/page"]))
                assert response.status_code == 200 and response.json()["kind"] == "MODULE_RESULT", response.text
                competitor.analyze.assert_awaited_once_with("https://competitor.example/page")
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())
