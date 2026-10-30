import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from tools import virtual_cmo_ablation as diagnostic
from tools.positioning_diagnostics import DiagnosticError, measurement
from tests.test_virtual_cmo_diagnostics import restored
from tests.test_strategy_builder import StrategyModel
from tests.test_graph_model_adapter import install_transport


@pytest.fixture(autouse=True)
def configured_model(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")


def captured():
    request = restored()
    return request, asyncio.run(diagnostic.capture_unprojected(request))


@pytest.mark.parametrize("case", diagnostic.CASES)
def test_cases_change_only_the_named_factor_and_never_mutate_baseline(case):
    _, replay = captured()
    original = deepcopy(replay.payload)
    value = diagnostic.variant(replay.payload, case)
    assert replay.payload == original
    if case == "baseline":
        assert value == original
        return
    if case.startswith("no_") or case == "equivalent_projection":
        assert value["text"]["format"]["schema"] != original["text"]["format"]["schema"]
        value["text"]["format"]["schema"] = deepcopy(original["text"]["format"]["schema"])
    elif case.startswith("core_"):
        assert value["input"][0] != original["input"][0]
        value["input"][0] = deepcopy(original["input"][0])
    elif case.startswith("upstream_"):
        data = json.loads(value["input"][1]["content"])
        previous = json.loads(original["input"][1]["content"])
        assert data["upstream_results"] != previous["upstream_results"]
        data["upstream_results"] = previous["upstream_results"]
        assert data == previous
        value["input"][1] = deepcopy(original["input"][1])
    elif case == "instructions_field":
        assert value.pop("instructions") == original["input"][0]["content"]
        value["input"].insert(0, deepcopy(original["input"][0]))
    else:
        key = {"model_gpt5": "model", "effort_medium": "reasoning", "budget_32000": "max_output_tokens"}[case]
        assert value[key] != original[key]
        value[key] = deepcopy(original[key])
    assert value == original


@pytest.mark.parametrize("authorized,hash_ok", [(False, True), (True, False)])
def test_live_requires_authorization_and_exact_payload_fingerprint(monkeypatch, authorized, hash_ok):
    request, replay = captured()
    def forbidden(*args, **kwargs):
        raise AssertionError("network attempted")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(DiagnosticError):
        asyncio.run(diagnostic.probe_once(request, replay.payload, authorized=authorized,
            expected_sha256=measurement(replay.payload)["sha256"] if hash_ok else "0" * 64))


@pytest.mark.parametrize("incomplete", [False, True])
def test_one_post_and_full_original_acceptance_boundary(monkeypatch, incomplete):
    request, replay = captured()
    raw = asyncio.run(StrategyModel(use_parents=True)(**replay.arguments))
    calls = []
    def respond(wire):
        calls.append(json.loads(wire.content))
        body = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                "output": [], "usage": {"input_tokens": 0, "output_tokens": 0}} if incomplete else {
                    "status": "completed", "output_text": raw}
        return httpx.Response(200, json=body)
    install_transport(monkeypatch, respond)
    payload = diagnostic.variant(replay.payload, "equivalent_projection")
    report = asyncio.run(diagnostic.probe_once(request, payload,
        expected_sha256=measurement(payload)["sha256"], authorized=True))
    assert calls == [payload]
    assert report["provider_calls"] == 1
    assert report["quality_accepted"] is (not incomplete)
    assert report["server_contract_valid"] is (not incomplete)
    assert raw not in json.dumps(report)


@pytest.mark.parametrize("reason,expected", [("max_output_tokens", "incomplete_empty_max_output_tokens"),
    ("content_filter", "incomplete_content_filter"), ("PRIVATE unknown reason", "incomplete_other")])
def test_incomplete_reason_is_safe_and_not_lost(monkeypatch, reason, expected):
    request, replay = captured()
    def respond(wire):
        return httpx.Response(200, json={"status": "incomplete", "incomplete_details": {"reason": reason},
            "output": [], "usage": {"output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}}})
    install_transport(monkeypatch, respond)
    report = asyncio.run(diagnostic.probe_once(request, replay.payload,
        expected_sha256=measurement(replay.payload)["sha256"], authorized=True))
    assert report["failure_reason"] == expected
    assert report["provider_calls"] == 1 and not report["quality_accepted"]
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("stage", ["construct", "enter"])
def test_pre_dispatch_client_failure_does_not_count_a_post(monkeypatch, stage):
    request, replay = captured()
    class BrokenClient:
        def __init__(self, **kwargs):
            if stage == "construct":
                raise ValueError("PRIVATE configuration")
        async def __aenter__(self):
            raise ValueError("PRIVATE configuration")
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(httpx, "AsyncClient", BrokenClient)
    report = asyncio.run(diagnostic.probe_once(request, replay.payload,
        expected_sha256=measurement(replay.payload)["sha256"], authorized=True))
    assert report["provider_calls"] == 0 and not report["quality_accepted"]
    assert "PRIVATE" not in json.dumps(report)
