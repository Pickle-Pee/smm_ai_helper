"""Read-only, offline aggregation of existing Responses telemetry (JSONL or text).

Run: python scripts/analyze_responses_logs.py worker.log [backend.log ...]
Input files are read in supplied chronological order; no network or app imports.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Iterable

MAX_LINE = 65536
ANOMALY = "incomplete_empty_max_output_tokens"
COUNTERS = ("input_tokens", "output_tokens", "reasoning_tokens")
MODULES = frozenset({"COMPETITOR_ANALYSIS", "POSITIONING", "CREATOR", "MARKET_ANALYSIS",
                     "VIRTUAL_CMO", "EXPERIMENTS", "BUSINESS_DIAGNOSTICS"})
KEYS = frozenset({"telemetry_version", "event", "provider_call_id", "outcome", "outcome_unknown",
                  "job_id", "run_id", "node_id", "module_id", "graph_attempt_id", "graph_attempt",
                  "usage_state", "token_usage_state", "reason", "failure_reason", "http_status",
                  *COUNTERS, *(c + "_state" for c in COUNTERS),
                  *(c + "_usage_state" for c in COUNTERS)})
PAIR = re.compile(r"\b([a-z][a-z0-9_]*)=([^\s]+)")
LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _label(value):
    return value if isinstance(value, str) and LABEL.fullmatch(value) else None


def _parse(line):
    if len(line) > MAX_LINE:
        return None
    record = {}
    try:
        raw = json.loads(line)
    except (ValueError, RecursionError):
        raw = None
    if isinstance(raw, dict):
        record = {k: v for k, v in raw.items() if k in KEYS and type(v) in (str, int, bool, type(None))}
        message = raw.get("message", "")
        if not isinstance(message, str):
            message = ""
    else:
        message = line
    # Plain logs have formatter fields before the message. Keep the last value.
    for key, value in PAIR.findall(message):
        if key in KEYS:
            record[key] = value
    if record.get("telemetry_version") == "llm_provider_request.v1":
        return record
    if "Structured model response rejected" in message and record.get("reason") == ANOMALY:
        return {"historical_anomaly": True}
    return None


def _unknown(record):
    return (record.get("event") != "finished"
            or record.get("outcome_unknown") in (True, "True", "true")
            or record.get("outcome") in {"timeout", "transport_error", "cancelled", "unknown"}
            or str(record.get("http_status")) == "408")


def _usage(record, name):
    if record.get("event") != "finished":
        return "unknown", None
    state = record.get(name + "_usage_state", record.get(name + "_state"))
    value = record.get(name)
    # Accept only provider-validated nonnegative integer counters. Never coerce bools.
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 10:
        value = int(value)
    if type(value) is int and 0 <= value <= 2**31 - 1 and state in {"reported", "reported_zero"}:
        return ("reported_zero" if value == 0 else "reported"), value
    if state == "not_applicable":
        return "not_applicable", None
    if state == "missing" or (state is None and record.get("usage_state") == "missing"):
        return "missing", None
    return "unknown", None


def analyze(lines: Iterable[str]):
    """Aggregate identities internally; return no user content or arbitrary labels."""
    calls = {}
    historical = ignored = duplicates = oversized = 0
    for line in lines:
        if len(line) > MAX_LINE:
            oversized += 1
            continue
        record = _parse(line)
        if record is None:
            ignored += 1
            continue
        if record.get("historical_anomaly"):
            historical += 1
            continue
        identity = _label(record.get("provider_call_id"))
        if identity is None or record.get("event") not in {"started", "finished"}:
            ignored += 1
            continue
        previous = calls.get(identity)
        if previous is not None:
            if previous.get("event") == "finished" or record.get("event") != "finished":
                duplicates += 1
                continue
            record = {**previous, **record}
        calls[identity] = record

    outcomes = Counter()
    modules = defaultdict(Counter)
    usage = {name: {"reported": 0, "reported_zero": 0, "missing": 0, "unknown": 0,
                    "not_applicable": 0, "known_tokens": 0} for name in COUNTERS}
    attempts, request_outcomes = set(), defaultdict(list)
    unbound = anomaly = repeated = 0
    prior_unknown = set()
    for identity, record in calls.items():
        unknown = _unknown(record)
        outcome = "unknown" if unknown else "successful" if record.get("outcome") == "success" else "unsuccessful"
        outcomes[outcome] += 1
        module = record.get("module_id")
        module = module if module in MODULES else "unbound_or_unrecognized"
        modules[module][outcome] += 1
        is_anomaly = record.get("reason", record.get("failure_reason")) == ANOMALY
        anomaly += is_anomaly
        modules[module]["incomplete_empty_max_output_tokens"] += is_anomaly
        job, run = _label(record.get("job_id")), _label(record.get("run_id"))
        attempt = _label(record.get("graph_attempt_id"))
        if job and attempt:
            attempts.add((job, attempt))
        elif job and str(record.get("graph_attempt", "")).isdigit():
            attempts.add((job, str(record["graph_attempt"])))
        request = ("run", run) if run else ("job", job) if job else None
        if request:
            request_outcomes[request].append(outcome != "successful")
        else:
            unbound += 1
        node = _label(record.get("node_id"))
        scope = (run, node) if run and node else (job,) if job else None
        if scope and scope in prior_unknown:
            repeated += 1
        if scope and unknown:
            prior_unknown.add(scope)
        for name in COUNTERS:
            state, tokens = _usage(record, name)
            usage[name][state] += 1
            if tokens is not None:
                usage[name]["known_tokens"] += tokens
    problem_count = sum(any(values) for values in request_outcomes.values())
    count = len(calls)
    return {
        "provider_calls": {"total": count, "successful": outcomes["successful"],
                           "unsuccessful": outcomes["unsuccessful"], "unknown": outcomes["unknown"]},
        "attempts": {"observed_graph_attempts_with_provider_calls": len(attempts),
                     "unbound_provider_calls": unbound},
        "incomplete_empty_max_output_tokens": {"provider_calls": anomaly,
            "fraction_of_observed_provider_calls": anomaly / count if count else None,
            "legacy_rejection_observations_without_call_id": historical},
        "problematic_requests": {"denominator": "distinct observed run_id, else job_id; excludes unbound calls",
            "observed": len(request_outcomes), "problematic": problem_count,
            "fraction": problem_count / len(request_outcomes) if request_outcomes else None},
        "by_module": {key: dict(value) for key, value in sorted(modules.items())},
        "token_usage": usage,
        "repeated_calls_after_unknown_outcome": repeated,
        "input_quality": {"ignored_lines": ignored, "oversized_lines": oversized,
                          "duplicate_or_superseded_events": duplicates},
        "limitations": [
            "Observed logs only: missing, rotated or pre-telemetry events cannot establish total requests or attempts.",
            "Legacy rejection observations have no unique call identity and are excluded from call counts and ratios.",
            "Started-only calls have unknown outcome; even a started event does not prove the provider received a POST.",
            "Supply files in chronological order. Repeated-after-unknown counts are candidates, not proof of automatic retry or charges.",
            "Unbound legacy calls cannot be grouped into user requests or workflow attempts.",
            "Known token totals are partial observed counters; zero, missing and unknown do not establish billing or actual cost.",
        ],
    }


def _lines(stream):
    while line := stream.readline(MAX_LINE + 1):
        if len(line) > MAX_LINE and not line.endswith("\n"):
            while chunk := stream.readline(MAX_LINE + 1):
                if chunk.endswith("\n"):
                    break
        yield line


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Chronological text/JSONL logs; '-' reads stdin")
    args = parser.parse_args(argv)
    def inputs():
        seen = set()
        for name in args.paths:
            path = Path(name).resolve() if name != "-" else "-"
            if path in seen:
                continue
            seen.add(path)
            if path == "-":
                yield from _lines(sys.stdin)
            else:
                with path.open(encoding="utf-8", errors="replace") as stream:
                    yield from _lines(stream)
    try:
        report = analyze(inputs())
    except OSError:
        parser.exit(2, "Cannot read one of the input logs.\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
