"""Offline transport + real governance methods over a transactional storage fake."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.llm.openai_text import chat, ModelResponseError
from app.llm.telemetry import graph_call_context, provider_hooks
from app.models import JobStatus
from app.module_execution import ModuleExecutorRegistry
from app.module_registry import ModuleId
from app.orchestration_runtime.contracts import GraphWorkItem, JOB_KIND, module_job_id
from app.orchestration_runtime.retry_policy import RetryGovernanceError, new_policy, decision, reserve
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.test_graph_model_adapter import install_transport
from tests.test_model_response_failures import empty_incomplete


NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
SECRET = "PRIVATE_SENTINEL_DO_NOT_LOG"


class Storage:
    def __init__(self, policy=True, budget=12000):
        self.item = GraphWorkItem(module_job_id("run", 1, "node"), "run", 1, "node", SECRET, 1)
        self.run = SimpleNamespace(status="running", input_json={"responses_retry": new_policy(1, budget)} if policy else {})
        self.lease = SimpleNamespace(claim_token=SECRET, lease_until=NOW + timedelta(seconds=330), attempts=1)
        self.job = SimpleNamespace(status=JobStatus.RUNNING, kind=JOB_KIND, marketing_run_id="run", workflow_step="node")
        self.commits = 0
        self.active_transactions = 0

    @asynccontextmanager
    async def sessions(self):
        store = self
        class Session:
            run = deepcopy(store.run)
            @asynccontextmanager
            async def begin(self):
                store.active_transactions += 1
                try:
                    yield
                    store.run = deepcopy(self.run)
                    store.commits += 1
                finally:
                    store.active_transactions -= 1
            async def scalar(self, query):
                return store.lease
            async def get(self, model, key):
                return store.job
        yield Session()

    def service(self):
        service = GraphExecutionService(self.sessions, executors=ModuleExecutorRegistry(), clock=lambda: NOW)
        async def run(session, run_id):
            return session.run
        service._run = run
        return service

    def restart(self):
        self.lease.attempts += 1
        self.lease.claim_token = "replacement_capability_" + str(self.lease.attempts)
        self.item = GraphWorkItem(self.item.job_id, "run", 1, "node", self.lease.claim_token, self.lease.attempts)
        return self.service()


async def invoke(service, store):
    request = SimpleNamespace(module_id=ModuleId.VIRTUAL_CMO, execution_id=store.item.job_id)
    hooks = await service.provider_hooks(store.item)
    with graph_call_context(store.item, request, None, hooks):
        # Intentionally legacy invocation: governed scope must disable local retry.
        return await chat([{"role": "user", "content": SECRET}], "test-model", max_output_tokens=4000)


@pytest.mark.parametrize("mode", [503, 408, "timeout", "network", "incomplete"])
def test_wire_retry_owner_and_no_local_cascade(monkeypatch, caplog, mode):
    store = Storage()
    sends = []
    def respond(request):
        assert store.active_transactions == 0
        assert store.run.input_json["responses_retry"]["calls"][-1]["outcome"] == "reserved"
        sends.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout(SECRET, request=request)
        if mode == "network":
            raise httpx.ReadError(SECRET, request=request)
        return httpx.Response(mode if isinstance(mode, int) else 200,
                              json=empty_incomplete() if mode == "incomplete" else {"error": SECRET},
                              headers={"x-request-id": "req_governance"})
    install_transport(monkeypatch, respond)
    async def exercise():
        service = store.service()
        with pytest.raises((httpx.HTTPError, ModelResponseError)) as caught:
            await invoke(service, store)
        assert len(sends) == 1
        retry, reason = await service.retry_decision(store.item, caught.value, True)
        assert retry is (mode in (503, "incomplete"))
        if retry:
            for _ in range(2):
                service = store.restart()
                with pytest.raises((httpx.HTTPError, ModelResponseError)) as caught:
                    await invoke(service, store)
                retry, reason = await service.retry_decision(store.item, caught.value, True)
            assert not retry and reason == "stop_retry_exhausted"
            service = store.restart()
            with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
                await invoke(service, store)
            assert len(sends) == 3
        else:
            service = store.restart()
            with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
                await invoke(service, store)
            assert len(sends) == 1
        calls = store.run.input_json["responses_retry"]["calls"]
        assert sum(c["max_output_tokens"] for c in calls) <= 12000
        assert len({c["provider_call_id"] for c in calls}) == len(calls)
        assert all(c["node_id"] == "node" and c["module_execution_id"] == store.item.job_id for c in calls)
        if mode == "incomplete":
            assert calls[0]["output_tokens_usage_state"] == "reported_zero"
        if mode == 408:
            assert calls[0]["request_id"] == "req_governance"
        assert SECRET not in str(calls) and SECRET not in caplog.text
        assert provider_hooks() is None
    asyncio.run(exercise())


def test_crash_after_reservation_prevents_replay_and_old_claim_is_fenced(monkeypatch):
    store = Storage()
    service = store.service()
    async def exercise():
        request = SimpleNamespace(module_id=ModuleId.VIRTUAL_CMO, execution_id=store.item.job_id)
        with graph_call_context(store.item, request, None):
            from app.llm.telemetry import correlation_fields
            fields = {**correlation_fields(), "provider_call_id": "call1", "max_output_tokens": 4000}
        before, after = await service.provider_hooks(store.item)
        await before(fields)  # Process dies here, no receipt; request may have been sent.
        old = store.item
        replacement = store.restart()
        with pytest.raises(RetryGovernanceError, match="inactive"):
            await after({**fields, "outcome": "success", "outcome_unknown": False})
        install_transport(monkeypatch, lambda r: pytest.fail("unknown outcome must not resend"))
        with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
            await invoke(replacement, store)
        assert old.claim_token != store.item.claim_token
    asyncio.run(exercise())


@pytest.mark.parametrize("expiration", [True, False], ids=["lease-expired", "cancelled"])
def test_cancellation_and_lease_expiration_leave_no_automatic_replay(monkeypatch, expiration):
    store = Storage()
    async def respond(request):
        if expiration:
            store.lease.lease_until = NOW
        raise asyncio.CancelledError()
    install_transport(monkeypatch, respond)
    async def exercise():
        with pytest.raises(RetryGovernanceError if expiration else asyncio.CancelledError):
            await invoke(store.service(), store)
        assert store.run.input_json["responses_retry"]["calls"][0]["outcome"] == ("reserved" if expiration else "unknown")
        store.lease.lease_until = NOW + timedelta(seconds=330)
        replacement = store.restart()
        with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
            await invoke(replacement, store)
    asyncio.run(exercise())


def test_aggregate_budget_across_nodes_and_success_receipt_crash(monkeypatch):
    store = Storage(budget=6000)
    install_transport(monkeypatch, lambda r: httpx.Response(200, json={"status": "completed", "output_text": "{}"}))
    async def exercise():
        assert (await invoke(store.service(), store))[0] == "{}"
        with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
            await invoke(store.restart(), store)
        policy = store.run.input_json["responses_retry"]
        with pytest.raises(RetryGovernanceError, match="budget_exhausted"):
            reserve(policy, {"node_id": "another", "max_output_tokens": 4000})
        assert len(policy["calls"]) == 1
    asyncio.run(exercise())


def test_unmarked_runs_keep_legacy_policy_and_settings_changes_do_not_upgrade_them():
    store = Storage(policy=False)
    async def exercise():
        service = store.service()
        service.responses_governance = True
        assert await service.provider_hooks(store.item) is None
        assert await service.retry_decision(store.item, TimeoutError(), True) == (True, "legacy_retry")
    asyncio.run(exercise())


def test_worker_unknown_outcome_terminal_and_cleanup_runs():
    store = Storage()
    service = store.service()
    service.claim = AsyncMock(return_value=store.item)
    service.load_work = AsyncMock(return_value=(object(), SimpleNamespace(
        module_id=ModuleId.VIRTUAL_CMO, execution_id=store.item.job_id)))
    service.fail, service.release_attempt = AsyncMock(), AsyncMock()
    worker = ModuleGraphWorker(service)
    worker.dispatcher.dispatch = AsyncMock(side_effect=httpx.ReadTimeout(SECRET))
    asyncio.run(worker.once())
    service.fail.assert_awaited_once_with(store.item, code="execution_invalid", retryable=False)
    service.release_attempt.assert_awaited_once_with(store.item)


def test_contract_error_cannot_reveal_transient_cause():
    from app.module_execution.errors import ModuleExecutionContractError
    error = ModuleExecutionContractError("private")
    response = httpx.Response(503, request=httpx.Request("POST", "https://provider.test"))
    error.__cause__ = httpx.HTTPStatusError("private", request=response.request, response=response)
    assert not decision(error)[0]


@pytest.mark.parametrize("mode", [400, 401, "refusal", "ordinary_incomplete", "invalid"])
def test_restart_after_terminal_receipt_never_repeats(monkeypatch, mode):
    store = Storage()
    sends = []
    def respond(request):
        sends.append(request)
        body = {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}
        if mode == "ordinary_incomplete":
            body = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "usage": {"output_tokens": 10}}
        elif mode == "invalid":
            body = {}
        return httpx.Response(mode if type(mode) is int else 200, json=body)
    install_transport(monkeypatch, respond)
    async def exercise():
        with pytest.raises((httpx.HTTPError, ModelResponseError)):
            await invoke(store.service(), store)
        # Crash before workflow failure/decision persistence, but after receipt.
        with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
            await invoke(store.restart(), store)
        assert len(sends) == 1
    asyncio.run(exercise())


def test_persisted_stop_decision_is_respected_after_restart(monkeypatch):
    store = Storage()
    sends = []
    def respond(request):
        sends.append(request)
        return httpx.Response(503, json={})
    install_transport(monkeypatch, respond)
    async def exercise():
        service = store.service()
        with pytest.raises(httpx.HTTPStatusError):
            await invoke(service, store)
        retry, _ = await service.retry_decision(store.item, ValueError(), True)
        assert not retry
        with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
            await invoke(store.restart(), store)
        assert len(sends) == 1
    asyncio.run(exercise())


def test_reservation_database_failure_prevents_send(monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    store = Storage()
    service = store.service()
    service._provider_receipt = AsyncMock(side_effect=SQLAlchemyError("unavailable"))
    install_transport(monkeypatch, lambda r: pytest.fail("reservation did not commit"))
    with pytest.raises(SQLAlchemyError):
        asyncio.run(invoke(service, store))
    assert store.run.input_json["responses_retry"]["calls"] == []
