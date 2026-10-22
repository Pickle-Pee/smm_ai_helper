"""Opt-in staging admission, using existing PostgreSQL receipt storage.

This is an attempt budget, not a dollar cap or a new execution queue. A reserved
call survives cancellation/restart. No automatic reset, lease stealing or replay
of provider requests is provided. Domain services still own committed results.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.llm.telemetry import correlation_fields
from app.models import MarketingArtifact, MarketingRun

WORKFLOW = "controlled_live.v1"
LEDGER_ID = "controlled_live_e2e_v1"
MAX_CALLS = 15
MAX_MENTOR = 7
MAX_PAYLOAD_BYTES = 131072
_operation = ContextVar("controlled_live_operation", default=None)


class ControlledLiveBlocked(RuntimeError):
    """Safe, content-free failure; never retry automatically."""


@contextmanager
def provider_operation(kind, *identity):
    key = hashlib.sha256(json.dumps([kind, *identity], sort_keys=True).encode()).hexdigest()
    token = _operation.set((kind, key))
    try:
        yield
    finally:
        _operation.reset(token)


def current_operation():
    graph = correlation_fields()
    if graph["correlation_state"] == "graph":
        return "graph", graph["job_id"], graph["run_id"]
    operation = _operation.get()
    if operation is None or operation[0] not in {"intent", "mentor"}:
        raise ControlledLiveBlocked("controlled_live_unscoped_call")
    return *operation, None


class ControlledLiveAdmission:
    def __init__(self, sessions):
        self.sessions = sessions
        self.experiment = settings.POSITIONING_OUTPUT_BUDGET_EXPERIMENT is not None
        self.ledger_id = "positioning_output_budget_20261023_v1" if self.experiment else LEDGER_ID

    async def reserve(self, payload):
        kind, operation, graph_run = current_operation()
        cap = payload["max_output_tokens"]
        if self.experiment:
            fmt = payload.get("text", {}).get("format", {})
            schema_hash = hashlib.sha256(json.dumps(fmt.get("schema"),
                ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if (kind != "graph" or correlation_fields().get("module_id") != "POSITIONING"
                    or payload["model"] != "gpt-5-mini"
                    or type(cap) is not int or cap != settings.POSITIONING_OUTPUT_BUDGET_EXPERIMENT
                    or cap not in (16000, 32000, 64000, 128000)
                    or payload.get("reasoning") != {"effort": "low"}
                    or fmt.get("type") != "json_schema" or fmt.get("strict") is not True
                    or schema_hash != "d0e0361566b1adb9b1ef59136713914f55d2f39675f206734068259bfffeb277"):
                raise ControlledLiveBlocked("controlled_live_experiment_payload_rejected")
        if (payload["model"] != settings.DEFAULT_TEXT_MODEL_HARD
                or type(cap) is not int
                or not 1 <= cap <= (128000 if self.experiment else 16000)
                or len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_PAYLOAD_BYTES):
            raise ControlledLiveBlocked("controlled_live_payload_rejected")
        key = hashlib.sha256(f"{kind}:{operation}".encode()).hexdigest()
        token = uuid.uuid4().hex
        async with self.sessions() as session, session.begin():
            await session.execute(insert(MarketingRun).values(
                run_id=self.ledger_id, workflow_type=WORKFLOW, status="ready",
                input_json={"model": settings.DEFAULT_TEXT_MODEL_HARD},
                state_json={"calls": 0, "mentor": 0, "graph_run": None},
            ).on_conflict_do_nothing(index_elements=[MarketingRun.run_id]))
            ledger = await session.scalar(select(MarketingRun).where(
                MarketingRun.run_id == self.ledger_id).with_for_update())
            if (ledger.workflow_type != WORKFLOW or ledger.status != "ready"
                    or ledger.input_json != {"model": settings.DEFAULT_TEXT_MODEL_HARD}):
                raise ControlledLiveBlocked("controlled_live_unresolved_call")
            state = dict(ledger.state_json)
            if self.experiment:
                budgets = list(state.get("budgets", []))
                order = (128000, 32000, 64000)
                if len(budgets) >= 3 or cap != order[len(budgets)]:
                    raise ControlledLiveBlocked("controlled_live_experiment_order_or_repeat")
                state["budgets"] = [*budgets, cap]
            if state["calls"] >= (3 if self.experiment else MAX_CALLS) or (kind == "mentor" and state["mentor"] >= MAX_MENTOR):
                raise ControlledLiveBlocked("controlled_live_budget_exhausted")
            if kind == "graph" and not self.experiment and state["graph_run"] not in (None, graph_run):
                raise ControlledLiveBlocked("controlled_live_strategy_limit")
            saved = await session.scalar(select(MarketingArtifact).where(
                MarketingArtifact.run_id == self.ledger_id, MarketingArtifact.artifact_key == key))
            if saved is not None:
                raise ControlledLiveBlocked("controlled_live_operation_already_attempted")
            state["calls"] += 1
            state["mentor"] += kind == "mentor"
            if kind == "graph":
                state["graph_run"] = graph_run
            state["active"] = {"key": key, "token": token}
            ledger.state_json, ledger.status = state, "in_flight"
            session.add(MarketingArtifact(run_id=self.ledger_id, artifact_key=key,
                artifact_type=WORKFLOW, step=kind, payload_json={
                    "state": "unknown", "token": token, "ordinal": state["calls"],
                    "model": payload["model"], "max_output_tokens": payload["max_output_tokens"],
                }))
        # Transaction commits before the first byte can be sent to the provider.
        return key, token

    async def finish(self, receipt, *, success):
        key, token = receipt
        async with self.sessions() as session, session.begin():
            ledger = await session.scalar(select(MarketingRun).where(
                MarketingRun.run_id == self.ledger_id).with_for_update())
            if (ledger is None or ledger.workflow_type != WORKFLOW or ledger.status != "in_flight"
                    or ledger.state_json.get("active") != {"key": key, "token": token}):
                raise ControlledLiveBlocked("controlled_live_receipt_conflict")
            saved = await session.scalar(select(MarketingArtifact).where(
                MarketingArtifact.run_id == self.ledger_id, MarketingArtifact.artifact_key == key))
            saved.payload_json = {**saved.payload_json, "state": "response_accepted" if success else "unknown"}
            ledger.status = "ready" if success else "blocked"
            ledger.state_json = {name: value for name, value in ledger.state_json.items() if name != "active"}


def admission():
    # Lazy import keeps ordinary transport imports/startup free of DB construction.
    from app.db import AsyncSessionLocal
    return ControlledLiveAdmission(AsyncSessionLocal)
