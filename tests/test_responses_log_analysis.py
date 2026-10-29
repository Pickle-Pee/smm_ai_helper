"""Historical diagnostics use local synthetic data and never import the app."""
import io
import json
import socket

import pytest

from scripts.analyze_responses_logs import MAX_LINE, _lines, analyze, main


def event(call, *, event="finished", outcome="success", **fields):
    return json.dumps({"telemetry_version": "llm_provider_request.v1", "provider_call_id": call,
        "event": event, "outcome": outcome, "run_id": "run1", "job_id": "job1",
        "node_id": "positioning", "module_id": "POSITIONING", "graph_attempt_id": "attempt1", **fields})


def test_deduplicates_plain_and_json_and_aggregates_usage():
    lines = [event("call1", event="started"), event("call1", input_tokens=5,
        input_tokens_state="reported", output_tokens=0, output_tokens_state="reported",
        reasoning_tokens_state="missing"),
        "LLM provider request telemetry_version=llm_provider_request.v1 provider_call_id=call2 event=finished "
        "outcome=rejected run_id=run1 job_id=job1 node_id=positioning module_id=POSITIONING "
        "graph_attempt_id=attempt2 reason=incomplete_empty_max_output_tokens usage_state=missing",
        event("call3", event="started", graph_attempt_id="attempt3")]
    report = analyze(lines + lines)
    assert report["provider_calls"] == {"total": 3, "successful": 1, "unsuccessful": 1, "unknown": 1}
    assert report["attempts"]["observed_graph_attempts_with_provider_calls"] == 3
    assert report["incomplete_empty_max_output_tokens"]["provider_calls"] == 1
    assert report["incomplete_empty_max_output_tokens"]["fraction_of_observed_provider_calls"] == pytest.approx(1 / 3)
    assert report["problematic_requests"]["fraction"] == 1
    assert report["token_usage"]["input_tokens"] == {"reported": 1, "reported_zero": 0,
        "known_tokens": 5, "missing": 1, "unknown": 1, "not_applicable": 0}
    assert report["token_usage"]["output_tokens"]["reported_zero"] == 1


@pytest.mark.parametrize("unknown", [dict(outcome="timeout"), dict(outcome="transport_error"),
    dict(outcome="http_error", http_status=408), dict(event="started"),
    dict(outcome="cancelled"), dict(outcome_unknown=True)])
def test_repeated_after_unknown_scopes_node_and_run(unknown):
    report = analyze([event("first", **unknown), event("other", node_id="other"),
                      event("other_run", run_id="other"), event("repeat", graph_attempt_id="attempt2")])
    assert report["provider_calls"]["unknown"] == 1
    assert report["repeated_calls_after_unknown_outcome"] == 1


def test_explicit_503_is_failed_not_unknown_and_legacy_limits_are_visible():
    report = analyze([event("a", outcome="http_error", http_status=503, run_id=None, job_id=None),
        "Structured model response rejected reason=incomplete_empty_max_output_tokens model=gpt-5",
        "private unrelated log", "not json {{", "x" * (MAX_LINE + 1)])
    assert report["provider_calls"] == {"total": 1, "successful": 0, "unsuccessful": 1, "unknown": 0}
    assert report["problematic_requests"]["fraction"] is None
    assert report["attempts"]["unbound_provider_calls"] == 1
    assert report["incomplete_empty_max_output_tokens"]["legacy_rejection_observations_without_call_id"] == 1
    assert report["input_quality"]["oversized_lines"] == 1
    assert report["limitations"]


@pytest.mark.parametrize("value,state", [(True, "reported"), (-1, "reported"), ("bad", "reported"),
                                         (999999999999, "reported"), (None, "null")])
def test_invalid_usage_never_becomes_zero(value, state):
    usage = analyze([event("a", input_tokens=value, input_tokens_state=state)])["token_usage"]["input_tokens"]
    assert usage["unknown"] == 1 and usage["reported_zero"] == 0 and usage["known_tokens"] == 0


def test_json_message_formatter_fields_and_secrets_never_echoed():
    message = "request_id=PRIVATE_SECRET LLM provider request telemetry_version=llm_provider_request.v1 " \
        "provider_call_id=a event=finished outcome=success module_id=PRIVATE_SECRET usage_state=missing"
    report = analyze([json.dumps({"message": message, "user_text": "PRIVATE_SECRET"}),
                      event("b", run_id="PRIVATE_SECRET", input_tokens_state="not_applicable")])
    assert report["provider_calls"]["total"] == 2
    assert "PRIVATE_SECRET" not in json.dumps(report)
    assert report["token_usage"]["input_tokens"]["not_applicable"] == 1


def test_cli_reads_only_deduplicates_paths_and_never_networks(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Historical analysis must never use network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    source = tmp_path / "worker.log"
    source.write_text(event("a") + "\n", encoding="utf-8")
    before = source.read_bytes()
    assert main([str(source), str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["provider_calls"]["total"] == 1
    assert source.read_bytes() == before


def test_bounded_reader_discards_large_line_then_recovers():
    report = analyze(_lines(io.StringIO("x" * (3 * MAX_LINE) + "\n" + event("a") + "\n")))
    assert report["input_quality"]["oversized_lines"] == 1
    assert report["provider_calls"]["total"] == 1


def test_empty_input_uses_unknown_denominator():
    report = analyze([])
    assert report["provider_calls"]["total"] == 0
    assert report["problematic_requests"]["fraction"] is None
    assert report["incomplete_empty_max_output_tokens"]["fraction_of_observed_provider_calls"] is None


def test_malformed_json_field_types_do_not_break_report():
    malformed = json.loads(event("a"))
    malformed.update(module_id=[], outcome={}, input_tokens_state=[], event=[])
    report = analyze([json.dumps(malformed), event("b", input_tokens=2, input_tokens_state="reported")])
    assert report["provider_calls"]["total"] == 1
    assert report["token_usage"]["input_tokens"]["known_tokens"] == 2
