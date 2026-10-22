"""Generative Mentor contracts, durable identity and case isolation with real SQL."""
import asyncio
import json
import uuid

import httpx
from sqlalchemy import select

from app.config import settings
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.mentor import CaseMentorService
from app.models import MarketingArtifact
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_case_mentor import DialogueModel
from tests.test_copilot_api import application, headers
from tests.test_copilot_api_postgresql import configured, payload, remove_actor, CONTEXT
from tests.test_graph_postgresql import state
from tests.test_strategy_builder import StrategyModel


async def completed_case(db, api, actor, **context):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
        result = await client.post("/copilot/execute", headers=headers(actor), json=payload(context={**CONTEXT, **context}))
        assert result.status_code == 202, result.text
        run_id = result.json()["run_id"]
    worker = ModuleGraphWorker(api.copilot.graph_service)
    for _ in range(10):
        if (await state(db, run_id))[0].status.startswith("completed"):
            return run_id
        assert await worker.once()
    raise AssertionError("case did not complete")


def test_dialogue_five_questions_restart_history_isolation_and_metrics(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = DialogueModel()
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=StrategyModel(use_parents=True), mentor_model=model)
        try:
            rid = await completed_case(mvp_database, api, actor, message="Проверить VK Рекламу")
            url = f"/copilot/runs/{rid}/mentor"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                questions = ["Почему выбрана VK Реклама?", "Почему не Telegram Ads?", "А если аудитория активнее в Telegram?",
                             "Тогда как распределить бюджет 50 000 ₽?", "Какие метрики подтвердят решение?"]
                answers = []
                for i, q in enumerate(questions):
                    answer = await client.post(url + "/questions", headers=headers(actor), json={"request_key": f"q{i}", "question": q})
                    assert answer.status_code == 200, answer.text
                    answers.append(" ".join(answer.json()["paragraphs"]))
                assert len(set(answers)) == 5
                assert "VK Реклама" in answers[0] and "гипотеза" in answers[0]
                assert "Telegram Ads" in answers[1] and "непроверенная альтернатива" in answers[1]
                assert "новая предпосылка" in answers[2]
                assert "50 000" in answers[3] and "не прогноз продаж" in answers[3]
                assert "конверсию" in answers[4] and "контрольной группы" in answers[4]
                assert all("Grow bookings" in answer for answer in answers)
                for i, call in enumerate(model.calls):
                    packet = json.loads(call["text"])
                    assert packet["current_question"] == questions[i]
                    assert len(packet["dialogue"]) == i
                    assert [turn["user"] for turn in packet["dialogue"]] == questions[:i]
                before = len(model.calls)
                replays = await asyncio.gather(*[client.post(url + "/questions", headers=headers(actor), json={"request_key": "q0", "question": questions[0]}) for _ in range(10)])
                assert all(row.status_code == 200 for row in replays)
                assert len(model.calls) == before
                conflict = await client.post(url + "/questions", headers=headers(actor), json={"request_key": "q0", "question": "Изменено"})
                assert conflict.status_code == 409
                prior = "AUDIENCE_PRIOR_ONLY_481"
                assert (await client.post(url + "/questions", headers=headers(actor), json={"request_key": "segment", "question": "Сегмент: " + prior})).status_code == 200
                report = await client.post(url + "/feedback", headers=headers(actor), json={"request_key": "report", "outcome": "hypothesis_tested", "notes": "Одна когорта", "metrics": "Расход: 15 000 ₽; Заявки: 30; Продажи: 3; Период: октябрь"})
                assert report.status_code == 200, report.text
                assert report.json()["analysis"]["calculations"]["cost_per_lead"] == "500 RUB"
            fresh_model = DialogueModel()
            fresh = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=StrategyModel(use_parents=True), mentor_model=fresh_model)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(fresh)), base_url="http://test") as client:
                history = await client.get(url + "/questions", headers=headers(actor))
                assert history.status_code == 200 and len(history.json()["turns"]) == 6
                assert not fresh_model.calls
                answer = await client.post(url + "/questions", headers=headers(actor), json={"request_key": "follow", "question": "А для этого сегмента что изменится?"})
                assert answer.status_code == 200 and prior in " ".join(answer.json()["paragraphs"])
                assert "500 RUB" in " ".join(answer.json()["paragraphs"])
                denied = await client.get(url + "/questions", headers=headers(actor + 1))
                assert denied.status_code == 404 and prior not in denied.text
            # A second contradictory case has no transcript or reports from the first.
            rid2 = await completed_case(mvp_database, fresh, actor, product="Manual paper books", target="Rural farms", message="PAPER_ONLY_912")
            from app.marketing_copilot.mentor_contracts import MentorQuestion
            await fresh.mentor.question(actor, rid2, MentorQuestion(request_key="new-case", question="Почему?"))
            packet = json.loads(fresh_model.calls[-1]["text"])
            assert packet["dialogue"] == [] and packet["feedback"] == []
            assert prior not in fresh_model.calls[-1]["text"] and "Manual paper books" in fresh_model.calls[-1]["text"]
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_concurrent_first_question_no_transaction_during_provider_and_unknown_restart(mvp_database, monkeypatch):
    from app.marketing_copilot.mentor_contracts import MentorQuestion
    from app.marketing_copilot.api_errors import ProviderUnavailable
    import pytest
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = DialogueModel()
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=StrategyModel(use_parents=True), mentor_model=model)
        try:
            rid = await completed_case(mvp_database, api, actor)
            entered, release = asyncio.Event(), asyncio.Event()
            async def blocked(**kwargs):
                entered.set()
                await release.wait()
                return await model(**kwargs)
            api.mentor.model_call = blocked
            request = MentorQuestion(request_key="concurrent", question="Почему?")
            tasks = [asyncio.create_task(api.mentor.question(actor, rid, request)) for _ in range(10)]
            await entered.wait()
            # This acquires the same source row lock: no provider I/O lock can remain.
            async with asyncio.timeout(2):
                await api.mentor.explain(actor, rid)
            release.set()
            answers = await asyncio.gather(*tasks)
            assert len(model.calls) == 1 and all(answer == answers[0] for answer in answers)
            async def never(**kwargs):
                raise TimeoutError("private provider information")
            api.mentor.model_call = never
            ambiguous = MentorQuestion(request_key="unknown", question="Как проверить?")
            with pytest.raises(ProviderUnavailable):
                await api.mentor.question(actor, rid, ambiguous)
            fresh = CaseMentorService(mvp_database, api.copilot.graph_service, model_call=model)
            with pytest.raises(ProviderUnavailable):
                await fresh.question(actor, rid, ambiguous)
            assert len(model.calls) == 1
            # Invalid successful provider output is not committed as an answer;
            # replay keeps the uncertain identity and never calls a provider again.
            calls = []
            async def malformed(**kwargs):
                calls.append(kwargs)
                return '{"paragraphs": []}'
            fresh.model_call = malformed
            invalid = MentorQuestion(request_key="invalid", question="Что известно?")
            with pytest.raises(ProviderUnavailable):
                await fresh.question(actor, rid, invalid)
            with pytest.raises(ProviderUnavailable):
                await fresh.question(actor, rid, invalid)
            assert len(calls) == 1
            # The service's own bounded timeout (not merely a provider-raised
            # exception) cancels the await and preserves unknown outcome.
            monkeypatch.setattr("app.marketing_copilot.mentor.PROVIDER_TIMEOUT_SECONDS", 0.01)
            timeout_calls = []
            async def slow(**kwargs):
                timeout_calls.append(kwargs)
                await asyncio.sleep(60)
            fresh.model_call = slow
            timed = MentorQuestion(request_key="timed", question="Как измерить?")
            with pytest.raises(ProviderUnavailable):
                await fresh.question(actor, rid, timed)
            with pytest.raises(ProviderUnavailable):
                await fresh.question(actor, rid, timed)
            assert len(timeout_calls) == 1
            # Crash after committed claim, before provider/result: expiry is unknown,
            # never authorization for automatic external work.
            orphan = MentorQuestion(request_key="orphan", question="Что дальше?")
            key = "question:" + __import__("hashlib").sha256(orphan.request_key.encode()).hexdigest()
            assert isinstance(await fresh._claim_question(actor, rid, orphan, key, "crashed-process"), dict)
            async with mvp_database() as session, session.begin():
                row = await session.scalar(select(MarketingArtifact).where(MarketingArtifact.run_id == fresh.companion_id(rid), MarketingArtifact.artifact_key == key))
                row.payload_json = {**row.payload_json, "expires": 0}
            with pytest.raises(ProviderUnavailable):
                await fresh.question(actor, rid, orphan)
            assert len(model.calls) == 1
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_distinct_concurrent_questions_serialize_and_use_first_answer(mvp_database, monkeypatch):
    from app.marketing_copilot.mentor_contracts import MentorQuestion
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = DialogueModel()
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY,
            module_model=StrategyModel(use_parents=True), mentor_model=model)
        entered, release, second_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        provider_requests = []
        try:
            rid = await completed_case(mvp_database, api, actor)
            original_claim = api.mentor._claim_question
            async def observed_claim(owner, run_id, request, key, token):
                claimed = await original_claim(owner, run_id, request, key, token)
                if request.request_key == "second" and claimed is None:
                    second_waiting.set()
                return claimed
            monkeypatch.setattr(api.mentor, "_claim_question", observed_claim)
            async def blocked(**kwargs):
                provider_requests.append(json.loads(kwargs["text"]))
                if len(provider_requests) == 1:
                    entered.set()
                    await release.wait()
                return await model(**kwargs)
            api.mentor.model_call = blocked
            first = asyncio.create_task(api.mentor.question(actor, rid,
                MentorQuestion(request_key="first", question="Сегмент: CLINIC_SEGMENT_582")))
            await entered.wait()
            second = asyncio.create_task(api.mentor.question(actor, rid,
                MentorQuestion(request_key="second", question="А для этого сегмента что изменится?")))
            async with asyncio.timeout(3):
                await second_waiting.wait()
            assert len(provider_requests) == 1 and not second.done()
            release.set()
            first_answer, second_answer = await asyncio.gather(first, second)
            assert len(provider_requests) == 2
            assert provider_requests[0]["dialogue"] == []
            assert provider_requests[1]["dialogue"] == [{"user": first_answer.question,
                "assistant": "\n".join(first_answer.paragraphs)[:2000]}]
            assert "CLINIC_SEGMENT_582" in " ".join(second_answer.paragraphs)
            history = await api.mentor.history(actor, rid)
            assert [turn.request_key for turn in history.turns] == ["first", "second"]
        finally:
            release.set()
            await remove_actor(mvp_database, actor)
    asyncio.run(check())
