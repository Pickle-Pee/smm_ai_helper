"""Durable HTTP clarification revisions; all provider transports are fake."""
import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import InterpretedRequestRecord, User
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.production import build_production_copilot_api
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application, headers, queue
from tests.test_copilot_api_postgresql import remove_actor
from tests.test_copilot_application import intent_model
from tests.test_marketing_copilot import PRODUCTION_STRATEGY_REQUEST
from tests.test_module_executors import FakeModel, analyzer
from tests.test_product_context import OWN, PRODUCT, AUDIENCE, JOB, PRICE, LEADER, extraction


def composed(sessions, provider, **kwargs):
    return build_production_copilot_api(sessions=sessions, queue=queue(),
        intent_model=provider, module_model=FakeModel(), analyzer=analyzer(), **kwargs)


async def execute(api, actor, request):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)),
                                base_url="http://test") as client:
        return await client.post("/copilot/execute", headers=headers(actor), json=request)


def test_owned_confirmation_reuses_interpretation_after_restart(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")

    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        message = PRODUCTION_STRATEGY_REQUEST
        provider = intent_model(IntentKind.MARKETING_STRATEGY, confidence=0.66,
            ambiguous=False, external_evidence_required=True, facts={
                "business_goal": "нужно до нового года выйти в плюс", "product": "садик частный",
                "target_or_target_hypothesis": "две возрастные группы 1,5-3 года и 3-6 лет",
                "geography": "Садик в анкудиноваке (Нижегородская область)"})
        initial_meaning = provider.return_value
        ambiguous = await intent_model(IntentKind.MARKETING_STRATEGY, ambiguous=True)()
        provider.side_effect = [initial_meaning, ambiguous]
        page = {"ok": True, "url": OWN, "final_url": OWN, "title": "Acme",
                "main_text_excerpt": "\n".join([PRODUCT, AUDIENCE, JOB, PRICE, LEADER])}
        site = SimpleNamespace(analyze_url=AsyncMock(return_value=SimpleNamespace(url_summaries=[page])))
        # Only product truth is acquired; the strategy's remaining business
        # requirements must survive confirmation without a generic rewrite.
        extractor = AsyncMock(return_value=extraction([json.loads(extraction())["statements"][0]]))
        request = dict(request_key=uuid.uuid4().hex, message=message, owned_site_url=OWN, context={})
        try:
            api = composed(mvp_database, provider, owned_analyzer=site, extractor=extractor)
            initial = await execute(api, actor, request)
            assert initial.status_code == 200 and initial.json()["kind"] == "NEEDS_INPUT", initial.text
            assert {key for group in initial.json()["alternatives"] for key in group} == {
                "customer_job_or_need", "relevant_alternative", "product_truth"}
            assert "request_context" not in initial.text
            owned = initial.json()["owned_site"]
            assert owned["candidates"]
            async with mvp_database() as session:
                owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
            persisted = await api.interpretations.load(owner, request["request_key"], message)
            assert persisted.intent.confidence == 0.66
            assert not persisted.intent.ambiguous
            snapshot = await api.snapshots.load(owner, request["request_key"], owned["snapshot_id"], OWN)
            assert snapshot is not None
            request["confirmation"] = dict(snapshot_id=owned["snapshot_id"],
                statement_ids=[owned["candidates"][0]["statement_id"]], confirmed=True, reference="Verified")

            # A separate engine and composition cannot inherit process-local continuation state.
            engine = create_async_engine(mvp_database.kw["bind"].url, poolclass=NullPool)
            try:
                restarted = composed(async_sessionmaker(engine, expire_on_commit=False), provider,
                                     owned_analyzer=site, extractor=extractor)
                confirmed = await execute(restarted, actor, request)
                assert confirmed.status_code == 200, confirmed.text
                missing = confirmed.json()
                assert missing["kind"] == "NEEDS_INPUT"
                assert {key for group in missing["alternatives"] for key in group} == {
                    "customer_job_or_need", "relevant_alternative"}
                assert "request_context" not in confirmed.text
                assert missing["owned_site"]["snapshot_id"] == owned["snapshot_id"]
                assert await restarted.interpretations.load(owner, request["request_key"], message) == persisted
                assert await restarted.snapshots.load(owner, request["request_key"], owned["snapshot_id"], OWN) == snapshot
                request["context"] = {"customer_job_or_need": "Reduce scheduling time",
                                      "relevant_alternative": "Manual spreadsheets"}
                started = await execute(restarted, actor, request)
                assert started.status_code == 202, started.text
                replay = await execute(restarted, actor, request)
                assert replay.status_code == 202 and replay.json()["run_id"] == started.json()["run_id"]
                changed = {**request, "context": {**request["context"], "customer_job_or_need": "Changed need"}}
                conflict = await execute(restarted, actor, changed)
                assert conflict.status_code == 409 and conflict.json()["code"] == "request_conflict"
            finally:
                await engine.dispose()
            provider.assert_awaited_once()
            site.analyze_url.assert_awaited_once()
            extractor.assert_awaited_once()
        finally:
            await remove_actor(mvp_database, actor)

    asyncio.run(check())


@pytest.mark.parametrize("change", ["message", "owner"])
def test_interpretation_revision_and_owner_isolation(mvp_database, monkeypatch, change):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")

    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        first_message = "Position first product for first audience."
        second_message = "Position second product for second audience." if change == "message" else first_message
        first = await intent_model(IntentKind.POSITIONING, facts={"product": "first product",
            "target_or_target_hypothesis": "first audience"})()
        second = await intent_model(IntentKind.POSITIONING, facts={"product": "second product",
            "target_or_target_hypothesis": "second audience"} if change == "message" else {})()
        provider = AsyncMock(side_effect=[first, second])
        api = composed(mvp_database, provider)
        request = dict(request_key=uuid.uuid4().hex, message=first_message, context={})
        try:
            initial = await execute(api, actor, request)
            assert initial.status_code == 200 and initial.json()["kind"] == "NEEDS_INPUT", initial.text
            second_actor = actor + 1 if change == "owner" else actor
            revised = await execute(api, second_actor, {**request, "message": second_message})
            assert revised.status_code == 200 and revised.json()["kind"] == "NEEDS_INPUT", revised.text
            assert provider.await_count == 2
            if change == "owner":
                assert "product" in {key for group in revised.json()["alternatives"] for key in group}
            replay = await execute(composed(mvp_database, provider), actor, request)
            assert replay.json() == initial.json()
            assert provider.await_count == 2
            async with mvp_database() as session:
                owners = select(User.id).where(User.telegram_id.in_([actor, actor + 1]))
                rows = (await session.scalars(select(InterpretedRequestRecord).where(
                    InterpretedRequestRecord.owner_id.in_(owners),
                    InterpretedRequestRecord.request_key == request["request_key"]))).all()
                assert len(rows) == 2
                first_row = next(row for row in rows if any(fact["value"] == "first product"
                    for fact in row.interpretation_json["projection"]["facts"]))
                assert first_row.interpretation_json["intent"] == json.loads(first)["intent"]
                other = next(row for row in rows if row is not first_row)
                expected_facts = {"second product", "second audience"} if change == "message" else set()
                assert {fact["value"] for fact in other.interpretation_json["projection"]["facts"]} == expected_facts
                if change == "message":
                    assert first_row.owner_id == other.owner_id
                    assert first_row.message_fingerprint != other.message_fingerprint
                else:
                    assert first_row.owner_id != other.owner_id
                    assert first_row.message_fingerprint == other.message_fingerprint
            api.queue.wake.assert_not_awaited()
        finally:
            await remove_actor(mvp_database, actor)
            await remove_actor(mvp_database, actor + 1)

    asyncio.run(check())


def test_corrupt_persisted_interpretation_fails_closed_at_http_boundary(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")

    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        provider = intent_model(IntentKind.POSITIONING)
        api = composed(mvp_database, provider)
        request = dict(request_key=uuid.uuid4().hex, message="Position our product.", context={})
        try:
            initial = await execute(api, actor, request)
            assert initial.status_code == 200 and initial.json()["kind"] == "NEEDS_INPUT", initial.text
            async with mvp_database() as session, session.begin():
                owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
                await session.execute(update(InterpretedRequestRecord).where(
                    InterpretedRequestRecord.owner_id == owner,
                    InterpretedRequestRecord.request_key == request["request_key"]
                ).values(interpretation_json={"intent": {"kind": "PRIVATE_CORRUPTION_SENTINEL"},
                                               "projection": {"facts": []}}))
            # Hydration must fail before semantic policy or executor use, and
            # cannot silently replace the immutable row with a provider retry.
            api.copilot.execute = AsyncMock(wraps=api.copilot.execute)
            rejected = await execute(api, actor, request)
            assert rejected.status_code == 500, rejected.text
            assert rejected.json()["code"] == "temporarily_unavailable"
            assert "PRIVATE_CORRUPTION_SENTINEL" not in rejected.text
            provider.assert_awaited_once()
            api.copilot.execute.assert_not_awaited()
            api.queue.wake.assert_not_awaited()
        finally:
            await remove_actor(mvp_database, actor)

    asyncio.run(check())
