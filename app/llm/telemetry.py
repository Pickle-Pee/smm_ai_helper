"""Task-local, content-free correlation for existing Responses HTTP calls."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import re


def safe_label(value):
    return value if type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else None


def safe_provider_id(value, kind):
    # Provider IDs have a dedicated shape; arbitrary label-shaped content is not an ID.
    pattern = r"resp_[A-Za-z0-9_-]{1,123}" if kind == "response" else (
        r"(?:req_[A-Za-z0-9_-]{1,124}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})"
    )
    return value if type(value) is str and re.fullmatch(pattern, value) else None


@dataclass(frozen=True, slots=True)
class GraphCallContext:
    job_id: str
    run_id: str
    plan_revision: int
    node_id: str
    module_id: str
    module_execution_id: str
    graph_attempt: int
    graph_attempt_id: str

    def __post_init__(self):
        for name in ("job_id", "run_id", "node_id", "module_id", "module_execution_id", "graph_attempt_id"):
            if safe_label(getattr(self, name)) is None:
                raise ValueError("Invalid graph telemetry identity")
        for value in (self.plan_revision, self.graph_attempt):
            if type(value) is not int or not 1 <= value <= 2 ** 31 - 1:
                raise ValueError("Invalid graph telemetry counter")


_context = ContextVar("graph_provider_context", default=None)
_timeout = ContextVar("graph_provider_timeout", default=None)


@contextmanager
def graph_call_context(item, request, timeout):
    context = GraphCallContext(
        job_id=item.job_id, run_id=item.run_id, plan_revision=item.plan_revision,
        node_id=item.node_id, module_id=request.module_id.value,
        module_execution_id=request.execution_id, graph_attempt=item.attempt,
        # A claim token is a fencing capability. Only its one-way digest is logged.
        graph_attempt_id=hashlib.sha256(item.claim_token.encode()).hexdigest(),
    )
    token = _context.set(context)
    timeout_token = _timeout.set(timeout)
    try:
        yield
    finally:
        _timeout.reset(timeout_token)
        _context.reset(token)


def correlation_fields():
    context = _context.get()
    if context is None:
        return {"correlation_state": "unbound"}
    return {"correlation_state": "graph", **{
        name: getattr(context, name) for name in context.__dataclass_fields__
    }}


def cancellation_outcome():
    timeout = _timeout.get()
    return "timeout" if timeout is not None and timeout.expired() else "cancelled"
