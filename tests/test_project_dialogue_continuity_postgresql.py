"""Document the bounded durable discussion contract without model-backed compaction."""
import asyncio
import copy
import json

from sqlalchemy import select

from app.models import Task
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService
from tests.postgresql_support import mvp_database
from tests.test_project_context_postgresql import cleanup, seed


def test_forty_turn_restart_keeps_source_and_last_twelve_but_not_early_decision(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        calls = []

        async def provider(**kwargs):
            calls.append({"packet": json.loads(kwargs["text"]), "instruction": kwargs["instruction"]})
            return json.dumps({"reply": "Generated hypothesis for " + calls[-1]["packet"]["current_question"]})

        def runtime():
            # No process-local memory survives construction of a fresh runtime.
            return ProjectContextService(mvp_database, ProjectHistoryService(mvp_database), model_call=provider)

        early_decision = "EARLY_DECISION_A_ONLY: user proposes testing tea subscriptions; unverified hypothesis"
        questions = [early_decision, *[f"A project follow-up {index:02}" for index in range(2, 41)]]
        try:
            async with mvp_database() as db:
                source_before = copy.deepcopy((await db.get(Task, int(sources[0][2:]))).result)
            selected = await runtime().switch(actor, actor, 0, sources[0])
            for index, question in enumerate(questions, 1):
                await runtime().message(actor, actor, selected["version"], f"tg:{actor}:{actor}:{index}", question)
            assert len(calls) == 40

            # A second project must not inherit the earlier decision or transcript.
            other = await runtime().switch(actor, actor, selected["version"], sources[1])
            await runtime().message(actor, actor, other["version"], f"tg:{actor}:{actor}:100", "B_PROJECT_ONLY question")
            other_packet = calls[-1]["packet"]
            assert "Business_B_ONLY" in json.dumps(other_packet)
            assert "Business_A_ONLY" not in json.dumps(other_packet)
            assert early_decision not in json.dumps(other_packet)
            assert other_packet["dialogue"] == []

            # Restart and return to A. History reads and activation spend no model calls.
            restarted = runtime()
            before_reads = len(calls)
            selected = await restarted.switch(actor, actor, other["version"], sources[0])
            recent_history = await restarted.discussion(actor, sources[0], limit=10)
            early_history = await restarted.discussion(actor, sources[0], limit=10, offset=30)
            assert len(recent_history["turns"]) == 10
            assert early_history["turns"][0]["question"] == early_decision
            assert early_history["turns"][0]["reply"] == "Generated hypothesis for " + early_decision
            assert len(calls) == before_reads

            await restarted.message(actor, actor, selected["version"], f"tg:{actor}:{actor}:101", "What have we decided?")
            packet = calls[-1]["packet"]
            assert packet["source_id"] == sources[0]
            assert packet["source"]["provenance"] == "saved_agent_task"
            assert "Business_A_ONLY" in json.dumps(packet["source"])
            assert "Business_B_ONLY" not in json.dumps(packet)
            assert "B_PROJECT_ONLY" not in json.dumps(packet)
            assert packet["dialogue"] == [
                {"question": question, "reply": "Generated hypothesis for " + question}
                for question in questions[-12:]
            ]
            assert packet["window"] == {"max_prior_turns": 12, "max_reply_characters_per_turn": 2000}
            # This is a checked limitation: old turns are durable and retrievable,
            # but no summary currently returns their decisions to the model.
            assert early_decision not in json.dumps(packet)
            assert "not verified facts" in packet["source"]["trust"]
            assert "generated" in calls[-1]["instruction"] and "hypotheses" in calls[-1]["instruction"]
            async with mvp_database() as db:
                assert (await db.get(Task, int(sources[0][2:]))).result == source_before
        finally:
            await cleanup(mvp_database, owner)

    asyncio.run(exercise())
