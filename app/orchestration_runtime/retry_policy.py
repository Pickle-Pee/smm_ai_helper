"""Bounded workflow-owned Responses reservations; no provider I/O or billing claims."""
from copy import deepcopy

import httpx

from app.llm.openai_text import ModelResponseError, ModelResponseFailureReason
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.common import ExecutorOutputError
from .errors import RuntimeContractError


class RetryGovernanceError(RuntimeContractError):
    pass


def new_policy(nodes, max_output_tokens):
    return {"version": 1, "max_calls": 3 * nodes, "max_node_calls": 3,
            "max_output_tokens": max_output_tokens, "calls": []}


def reserve(policy, fields):
    policy = deepcopy(policy)
    if policy.get("version") != 1:
        raise RetryGovernanceError("unsupported_retry_policy")
    calls = policy["calls"]
    node_calls = [c for c in calls if c["node_id"] == fields["node_id"]]
    # A completed receipt is not an accepted/persisted module artifact. Repeating
    # it after a crash is also unsafe; accepted artifacts bypass model execution.
    if any(not (
        not c.get("retry_decision", "").startswith("stop_") and (
            c["outcome"] == "http_error" and c.get("http_status") in {429, 500, 502, 503, 504}
            or c["outcome"] == "rejected" and c.get("failure_reason") == "incomplete_empty_max_output_tokens")
    ) for c in node_calls):
        raise RetryGovernanceError("previous_outcome_requires_owner_decision")
    if (len(calls) >= policy["max_calls"] or len(node_calls) >= policy["max_node_calls"]
            or sum(c["max_output_tokens"] for c in calls) + fields["max_output_tokens"] > policy["max_output_tokens"]):
        raise RetryGovernanceError("responses_budget_exhausted")
    calls.append({**fields, "outcome": "reserved"})
    return policy


def complete(policy, receipt):
    policy = deepcopy(policy)
    call = next((c for c in policy["calls"] if c["provider_call_id"] == receipt["provider_call_id"]), None)
    if call is None or call["outcome"] != "reserved":
        raise RetryGovernanceError("invalid_provider_receipt")
    call.update(receipt)
    call["outcome"] = "unknown" if receipt["outcome_unknown"] else receipt["outcome"]
    return policy


def decision(exc):
    """One owner decides; transport loss and HTTP 408 always stop automatically."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, RetryGovernanceError):
            return False, "stop_governance"
        if isinstance(exc, ModelResponseError):
            retry = exc.reason is ModelResponseFailureReason.INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS
            return retry, "retry_empty_anomaly" if retry else "stop_response_rejected"
        if isinstance(exc, (TimeoutError, httpx.TransportError)):
            return False, "stop_unknown_outcome"
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            retry = status in {429, 500, 502, 503, 504}
            return retry, "retry_explicit_http" if retry else (
                "stop_unknown_outcome" if status == 408 else "stop_http")
        # Contract failures are terminal even when their cause was transient.
        if isinstance(exc, (ValueError, RuntimeContractError, ModuleExecutionContractError, ExecutorOutputError)):
            return False, "stop_contract"
        exc = exc.__cause__
    return False, "stop_execution_invalid"
