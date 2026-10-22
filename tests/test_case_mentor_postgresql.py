"""HTTP/worker/real PostgreSQL case explanation, concurrency and restart."""
import asyncio
import copy
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.mentor import CaseMentorService
from app.models import MarketingArtifact
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application, headers
from tests.test_copilot_api_postgresql import configured, payload, remove_actor
from tests.test_graph_postgresql import state
from tests.test_strategy_builder import StrategyModel
from tests.test_case_mentor import DialogueModel
from tests.test_telegram_copilot import context, message, text_sent


def test_case_mentor_concurrency_restart_security_feedback_and_followup(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = StrategyModel(use_parents=True)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=model, mentor_model=DialogueModel())
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload())
                assert response.status_code == 202, response.text
                run_id = response.json()["run_id"]
                url = f"/copilot/runs/{run_id}/mentor"
                absent = await client.get(url, headers=headers(actor))
                assert absent.status_code == 404
                premature = await client.post(url, headers=headers(actor))
                assert premature.status_code == 409
                worker = ModuleGraphWorker(api.copilot.graph_service)
                for _ in range(10):
                    if (await state(mvp_database, run_id))[0].status.startswith("completed"):
                        break
                    assert await worker.once()
                source_run, jobs, artifacts = await state(mvp_database, run_id)
                before = copy.deepcopy([(row.artifact_key, row.payload_json) for row in artifacts])
                call_count = len(model.calls)
                with monkeypatch.context() as failure:
                    failure.setattr(api.mentor, "_create", AsyncMock(side_effect=SQLAlchemyError("offline write failure")))
                    rejected = await client.post(url, headers=headers(actor))
                    assert rejected.status_code == 503
                    assert (await client.get(f"/copilot/runs/{run_id}", headers=headers(actor))).status_code == 200
                    assert (await client.get(url, headers=headers(actor))).status_code == 404
                replies = await asyncio.gather(*[client.post(url, headers=headers(actor)) for _ in range(10)])
                assert all(reply.status_code == 200 for reply in replies), [reply.text for reply in replies]
                saved = replies[0].json()
                assert all(reply.json() == saved for reply in replies)
                assert len(saved["sections"]) == 8
                assert len(model.calls) == call_count
                async with mvp_database() as session:
                    rows = (await session.scalars(select(MarketingArtifact).where(
                        MarketingArtifact.run_id == CaseMentorService.companion_id(run_id)))).all()
                    assert len(rows) == 1
                # New production composition represents restart; provider capability
                # is present but must never be called when reading saved explanation.
                unavailable_provider = AsyncMock(side_effect=RuntimeError("offline provider unavailable"))
                restarted = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=unavailable_provider, mentor_model=DialogueModel())
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(restarted)), base_url="http://test") as fresh:
                    replay = await fresh.get(url, headers=headers(actor))
                    assert replay.status_code == 200 and replay.json() == saved
                    for method, path, data in [("GET", url, None), ("POST", url, None),
                            ("POST", url + "/questions", {"request_key": "foreign", "question": "Почему?"}),
                            ("POST", url + "/feedback", {"request_key": "foreign", "outcome": "worked", "notes": "yes"})]:
                        foreign = await fresh.request(method, path, headers=headers(actor + 1), json=data)
                        assert foreign.status_code == 404
                    question = {"request_key": "question-one", "question": "Почему не использовать контекстную рекламу?"}
                    answer = await fresh.post(url + "/questions", headers=headers(actor), json=question)
                    assert answer.status_code == 200, answer.text
                    assert answer.json()["focus"] == "alternative"
                    assert any("не сравнивались" in text for text in answer.json()["paragraphs"])
                    assert any("Grow bookings" in text for text in answer.json()["paragraphs"])
                    question_replays = await asyncio.gather(*[fresh.post(url + "/questions", headers=headers(actor), json=question) for _ in range(10)])
                    assert all(reply.status_code == 200 and reply.json() == answer.json() for reply in question_replays)
                    conflict = await fresh.post(url + "/questions", headers=headers(actor), json={**question, "question": "Другой бюджет?"})
                    assert conflict.status_code == 409
                    report = {"request_key": "feedback-one", "outcome": "did_not_work", "notes": "Стратегию применили, заявок не стало больше", "metrics": "За неделю: 4 заявки, до теста: 5"}
                    feedback = await fresh.post(url + "/feedback", headers=headers(actor), json=report)
                    assert feedback.status_code == 200 and feedback.json()["verification"] == "user_reported"
                    assert (await fresh.post(url + "/feedback", headers=headers(actor), json=report)).json() == feedback.json()
                    followup = await fresh.post(url + "/questions", headers=headers(actor), json={"request_key": "question-two", "question": "Что проверить в первую очередь?"})
                    assert followup.status_code == 200, followup.text
                    assert followup.json()["focus"] == "verification"
                    assert any("За неделю: 4 заявки" in p for p in followup.json()["paragraphs"])
                    assert any("не независимо проверено" in p for p in followup.json()["paragraphs"])
                    assert len(model.calls) == call_count
                    unavailable_provider.assert_not_awaited()
                    async with mvp_database() as session:
                        rows = (await session.scalars(select(MarketingArtifact).where(
                            MarketingArtifact.run_id == CaseMentorService.companion_id(run_id)))).all()
                        assert len(rows) == 4  # one explanation, two questions, one explicit report
                    # Source API still passes its strict artifact validation and
                    # source graph lifecycle/results did not change.
                    public = await fresh.get(f"/copilot/runs/{run_id}", headers=headers(actor))
                    assert public.status_code == 200 and public.json()["strategy"] is not None
                after, after_jobs, after_artifacts = await state(mvp_database, run_id)
                assert [(row.artifact_key, row.payload_json) for row in after_artifacts] == before
                assert after.updated_at == source_run.updated_at
                assert [(j.status, j.updated_at) for j in after_jobs] == [(j.status, j.updated_at) for j in jobs]
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_telegram_case_mentor_real_http_restart_followup_and_report(mvp_database, monkeypatch):
    """Fake only Telegram sends/provider; bot HTTP, authorization and stores are real."""
    from bot.copilot_flow import run_callback
    from bot.handlers import mentor

    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    monkeypatch.setattr(settings, "API_BASE_URL", "http://backend")

    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = StrategyModel(use_parents=True)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=model, mentor_model=DialogueModel())
        backend_app = [application(api)]
        original_client = httpx.AsyncClient
        try:
            async with original_client(transport=httpx.ASGITransport(app=backend_app[0]), base_url="http://backend") as client:
                created = await client.post("/copilot/execute", headers=headers(actor), json=payload())
                assert created.status_code == 202, created.text
                run_id = created.json()["run_id"]
                worker = ModuleGraphWorker(api.copilot.graph_service)
                for _ in range(10):
                    if (await state(mvp_database, run_id))[0].status.startswith("completed"):
                        break
                    assert await worker.once()

            source_run, source_jobs, source_artifacts = await state(mvp_database, run_id)
            artifacts_before = copy.deepcopy([(row.artifact_key, row.payload_json) for row in source_artifacts])
            calls_before = len(model.calls)
            requests = []

            async def capture(request):
                requests.append((request.method, request.url.path, request.headers["X-Telegram-User-ID"]))

            def transport_client(**kwargs):
                return original_client(transport=httpx.ASGITransport(app=backend_app[0]),
                    event_hooks={"request": [capture]}, **kwargs)

            # Keep backend.request and actor_headers intact, replacing only the
            # network transport to target the actual authenticated ASGI routes.
            monkeypatch.setattr(httpx, "AsyncClient", transport_client)
            fsm = context(actor)
            bot_message = message(actor=actor)
            bot_message.from_user = SimpleNamespace(id=999999)  # Telegram's bot owns the original message.
            callback = SimpleNamespace(message=bot_message, from_user=SimpleNamespace(id=actor),
                data=run_callback(run_id).replace("cs:", "cm:"), answer=AsyncMock())
            await mentor.explain(callback, fsm)
            assert await fsm.get_state() == mentor.MentorStates.question.state
            assert (await fsm.get_data())["mentor_run_id"] == run_id
            rendered = text_sent(bot_message)
            for expected in ("Цель решения", "Grow bookings", "Основания выбора", "Validate the supplied scheduling hypothesis", "Практическая проверка"):
                assert expected in rendered

            comparison = message("Почему не использовать контекстную рекламу?", mid=2, actor=actor)
            await mentor.question(comparison, fsm)
            assert "не сравнивались" in text_sent(comparison)
            assert "Grow bookings" in text_sent(comparison)
            report = message("/case_feedback did_not_work | Применили стратегию, роста нет | Неделя: 4 заявки вместо 5", mid=3, actor=actor)
            await mentor.feedback(report, fsm)
            assert "не независимая проверка" in text_sent(report)
            followup = message("Что проверить в первую очередь?", mid=4, actor=actor)
            await mentor.question(followup, fsm)
            assert "Метрика: Qualified inquiry rate" in text_sent(followup)
            assert "Неделя: 4 заявки вместо 5" in text_sent(followup)
            assert "не независимо проверено" in text_sent(followup)

            # Fresh API composition plus empty bot FSM model a restart. The old
            # compact callback still resolves the same owner-scoped saved case.
            unavailable_provider = AsyncMock(side_effect=RuntimeError("offline provider unavailable"))
            restarted = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=unavailable_provider, mentor_model=DialogueModel())
            backend_app[0] = application(restarted)
            restarted_fsm = context(actor)
            reopened = message(actor=actor)
            reopened.from_user = SimpleNamespace(id=999999)
            fresh_callback = SimpleNamespace(message=reopened, from_user=SimpleNamespace(id=actor),
                data=callback.data, answer=AsyncMock())
            await mentor.explain(fresh_callback, restarted_fsm)
            assert text_sent(reopened) == rendered
            assert (await restarted_fsm.get_data())["mentor_run_id"] == run_id
            after_restart = message("Что проверить?", mid=5, actor=actor)
            await mentor.question(after_restart, restarted_fsm)
            assert "Неделя: 4 заявки вместо 5" in text_sent(after_restart)
            assert len(model.calls) == calls_before
            unavailable_provider.assert_not_awaited()
            assert requests and all(owner == str(actor) for _, _, owner in requests)
            assert {path.rsplit("/", 1)[-1] for _, path, _ in requests} == {"mentor", "questions", "feedback"}

            foreign_message = message(actor=actor + 1)
            foreign_callback = SimpleNamespace(message=foreign_message, from_user=SimpleNamespace(id=actor + 1),
                data=callback.data, answer=AsyncMock())
            foreign_fsm = context(actor + 1)
            await mentor.explain(foreign_callback, foreign_fsm)
            assert "Не удалось открыть разбор" in text_sent(foreign_message)
            assert "Grow bookings" not in text_sent(foreign_message)
            assert await foreign_fsm.get_state() is None
            assert requests[-1][2] == str(actor + 1)

            async with mvp_database() as session:
                saved_rows = (await session.scalars(select(MarketingArtifact).where(
                    MarketingArtifact.run_id == CaseMentorService.companion_id(run_id)))).all()
                assert len(saved_rows) == 5  # explanation, three questions and one report
            after, jobs_after, artifacts_after = await state(mvp_database, run_id)
            assert [(row.artifact_key, row.payload_json) for row in artifacts_after] == artifacts_before
            assert after.updated_at == source_run.updated_at
            assert [(row.status, row.updated_at) for row in jobs_after] == [(row.status, row.updated_at) for row in source_jobs]
        finally:
            await remove_actor(mvp_database, actor)

    asyncio.run(check())
