"""Standalone read-only EXPERIMENTS replay. Raw requests never leave memory offline."""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import json
import logging
import os
from pathlib import Path

from tools.positioning_diagnostics import (
    DiagnosticError, Replay, SNAPSHOT_LIMIT, _Captured, capture_wire, compact,
    live_probe, measurement, metadata as common_metadata,
    restore_database as shared_database, restore_snapshot as shared_snapshot,
)
from tools.positioning_schema_diagnostics import (
    ANNOTATIONS, SchemaDiagnosticError, inline_refs, is_support_or, nodes, schema_metadata,
)

INCIDENT = {"input": 102054, "instructions": 53096, "schema": 7199}
CASES = ("baseline", "collapse_single_support_anyof", "no_annotations", "inline_refs")
HARD_CALL_LIMIT = 4


async def restore_snapshot(snapshot, *, run_id, job_id):
    from app.module_registry import ModuleId
    return await shared_snapshot(snapshot, run_id=run_id, job_id=job_id, module_id=ModuleId.EXPERIMENTS)


async def restore_database(*, run_id, job_id):
    from app.module_registry import ModuleId
    return await shared_database(run_id=run_id, job_id=job_id, module_id=ModuleId.EXPERIMENTS)


async def capture_request(request):
    from app.module_execution.executors.experiments import ExperimentsExecutor
    arguments = {}

    async def capture(**kwargs):
        arguments.update(kwargs)
        raise _Captured()

    try:
        await ExperimentsExecutor(model_call=capture).execute(request)
    except _Captured:
        pass
    if not arguments:
        raise DiagnosticError("request_not_executable")
    # Incident model only; output budget and all other arguments are production-owned.
    return Replay(await capture_wire(arguments, model="gpt-5-mini"), arguments)


def schema_matrix(payload):
    """Proof-gated equivalents only; unsupported rewrites stay unavailable."""
    from app.module_execution.executors.provider_schema import (
        SchemaProjectionError, collapse_single_support_anyof,
    )
    payloads, reports = {}, {}
    for case in CASES:
        candidate = deepcopy(payload)
        schema = candidate["text"]["format"]["schema"]
        try:
            if case == "collapse_single_support_anyof":
                schema = collapse_single_support_anyof(schema)
            elif case == "inline_refs":
                # Ref expansion proof excludes scope-sensitive evaluation keywords.
                if any(any(k in n for k in ("$id", "$anchor", "$dynamicAnchor", "$dynamicRef",
                        "unevaluatedProperties", "unevaluatedItems")) for n in nodes(schema)):
                    raise SchemaDiagnosticError("scope_sensitive_schema")
                schema = inline_refs(schema)
            elif case == "no_annotations":
                for node in nodes(schema):
                    for key in ANNOTATIONS:
                        node.pop(key, None)
            candidate["text"]["format"]["schema"] = schema
            changed = schema != payload["text"]["format"]["schema"]
            reports[case] = {"available": True, "changed": changed,
                "equivalence": "baseline" if case == "baseline" else "assertion_equivalent",
                "schema": measurement(schema), "structure": schema_metadata(schema)}
            # A no-op is measured but cannot be mistaken for a useful A/B arm.
            if case == "baseline" or changed:
                payloads[case] = candidate
        except (SchemaProjectionError, SchemaDiagnosticError):
            reports[case] = {"available": False, "changed": False, "equivalence": "proof_refused"}
    return payloads, reports


def duplication_metadata(data):
    """Exact leaf repetition is structural evidence, not a safe removal proposal."""
    components = ("context", "local_evidence", "upstream_results")

    def leaves(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from leaves(child)
        elif isinstance(value, list):
            for child in value:
                yield from leaves(child)
        elif isinstance(value, str) and value:
            yield value

    counters = {key: Counter(leaves(data[key])) for key in components}
    pairs = []
    for i, left in enumerate(components):
        for right in components[i + 1:]:
            overlap = counters[left] & counters[right]
            pairs.append({"components": [left, right], "distinct_equal_string_leaves": len(overlap),
                "matched_occurrences": sum(overlap.values()),
                "matched_utf8_bytes": sum(len(v.encode("utf-8")) * count for v, count in overlap.items())})
    # More specific structural relations: fact -> evidence, payload -> claim.
    facts = data["context"]["known_facts"]
    evidence = data["local_evidence"]
    repeated_facts = [f["value"] for f in facts if any(
        compact(f["value"]) == compact(e["value"]) for e in evidence)]
    matched_fields = matched_bytes = 0
    for upstream in data["upstream_results"]:
        result = upstream["result"]
        claims = {c["declared_output_name"]: c for c in result["normalized_result"]["claims"]}
        for statement in result["payload"].get("outputs", []):
            claim = claims.get(statement.get("output_name"))
            if not claim:
                continue
            value = claim["value"]
            try:
                structured = json.loads(value)
            except (ValueError, TypeError):
                structured = {}
            structured = structured if isinstance(structured, dict) else {}
            for key, normalized in (("text", "summary"), ("items", "items"), ("numeric_context", "numeric_context")):
                if key in statement and compact(statement[key]) == compact(
                        value if key == "text" and not structured else structured.get(normalized)):
                    matched_fields += 1
                    matched_bytes += measurement(statement[key])["bytes"]
    return {"method": "exact_values_and_string_leaves_not_semantic_deduplication",
        "pairs": pairs, "fact_values_repeated_in_evidence": len(repeated_facts),
        "repeated_fact_value_bytes": sum(measurement(v)["bytes"] for v in repeated_facts),
        "payload_claim_equal_fields": matched_fields, "payload_claim_equal_field_bytes": matched_bytes,
        "safe_to_remove": False}


def metadata(replay, request):
    from app.module_execution.executors.experiments import strategic_parents
    from app.module_execution.executors.common import parent_claims
    report = common_metadata(replay)
    report["baseline_mode"] = "current_production_builders_incident_model"
    report["model_matches_incident"] = replay.payload["model"] == "gpt-5-mini"
    report["output_budget"] = {"actual": replay.payload["max_output_tokens"], "incident": 16000,
        "matches": replay.payload["max_output_tokens"] == 16000}
    report["incident_comparison"] = {key: {"expected_bytes": size,
        "actual_bytes": report["components"][key]["bytes"],
        "delta_bytes": report["components"][key]["bytes"] - size,
        "matches": report["components"][key]["bytes"] == size} for key, size in INCIDENT.items()}
    report["reconstruction"] = {"upstream_artifacts": len(request.upstream_results),
        "constraints": len(request.context_packet.constraints),
        "target_failure_excluded_from_dispatch_coverage": True,
        "accepted_ancestor_closure_validated": True}
    report["size_conventions"] = {"input_and_instructions": "exact_wire_string_utf8",
        "schema": "canonical_compact_sorted_json_utf8",
        "schema_default_json_bytes": len(json.dumps(replay.payload["text"]["format"]["schema"], ensure_ascii=False).encode("utf-8"))}
    report["historical_fidelity"] = "current_builders_and_current_accepted_graph_not_original_dispatch_snapshot"
    data = json.loads(replay.payload["input"][1]["content"])
    report["duplication"] = duplication_metadata(data)
    schema = replay.payload["text"]["format"]["schema"]
    ors = [n for n in nodes(schema) if is_support_or(n)]
    report["length_bounds"] = {key: [{"bound": value, "occurrences": count}
        for value, count in sorted(Counter(n[key] for n in nodes(schema) if key in n).items())]
        for key in ("minLength", "maxLength", "minItems", "maxItems")}
    report["support_or_branches"] = {"single": sum(len(n["anyOf"]) == 1 for n in ors),
        "two": sum(len(n["anyOf"]) == 2 for n in ors)}
    design = schema["$defs"]["ExperimentDesign"]
    refs = design["properties"]["related_strategic_claim_ids"]
    report["experiment_design"] = {"structure": schema_metadata(design),
        "related_strategic_claim_ids": {"min_items": refs["minItems"], "max_items": refs["maxItems"],
            "schema_enum_bound": "enum" in refs.get("items", {}), "schema_ref_bound": "$ref" in refs.get("items", {}),
            "server_requires_unique": True, "server_requires_strategic_subset": True},
        "strategic_parent_count": len(strategic_parents(request)),
        "other_allowed_parent_count": len(parent_claims(request)) - len(strategic_parents(request)),
        "every_output_requires_strategic_parent": True,
        "eligibility": "accepted_within_scope_POSITIONING_or_VIRTUAL_CMO_HYPOTHESIS",
        "materiality_field_checked_by_executor": False,
        "schema_kinds_broader_than_runtime": True,
        "runtime_kinds": ["HYPOTHESIS", "RECOMMENDATION"],
        "bounds": {key: {bound: prop[bound] for bound in ("minLength", "maxLength", "minItems", "maxItems") if bound in prop}
                   for key, prop in design["properties"].items()},
        "numeric_context_is_not_numeric_support": True,
        "constraints_preserved_verbatim": True}
    report["hypotheses"] = {"schema": "support_OR_and_refs_require_controlled_schema_only_AB",
        "context": "repeated_values_require_separate_semantic_review_before_any_input_change",
        "root_cause_proven": False}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only EXPERIMENTS diagnostics; offline by default")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--database-read", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--max-calls", type=int)
    args = parser.parse_args(argv)
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        if ((not args.live and (args.case or args.max_calls is not None)) or
                (args.live and (not args.case or type(args.max_calls) is not int or
                    not 1 <= args.max_calls <= HARD_CALL_LIMIT or len(args.case) > args.max_calls or
                    len(args.case) != len(set(args.case))))):
            print('{"error":"live_policy_rejected"}')
            return 2
        if not args.database_read and not args.live:
            os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://offline:offline@localhost/offline")
            os.environ.setdefault("TELEGRAM_BOT_TOKEN", "offline")
            os.environ.setdefault("OPENAI_API_KEY", "offline")

        async def execute():
            if args.snapshot:
                with args.snapshot.open("rb") as stream:
                    raw = stream.read(SNAPSHOT_LIMIT + 1)
                if len(raw) > SNAPSHOT_LIMIT:
                    raise DiagnosticError("snapshot_too_large")
                request = await restore_snapshot(json.loads(raw), run_id=args.run_id, job_id=args.job_id)
            else:
                request = await restore_database(run_id=args.run_id, job_id=args.job_id)
            replay = await capture_request(request)
            payloads, matrix = schema_matrix(replay.payload)
            report = metadata(replay, request)
            report["schema_matrix"] = matrix
            if args.live:
                # Missing/proof-refused/no-op arms are rejected before HTTP construction.
                report["probes"] = await live_probe(payloads, cases=args.case,
                    max_calls=args.max_calls, opt_in=True)
            print(compact(report))

        try:
            asyncio.run(execute())
        except Exception:
            print('{"error":"diagnostic_failed"}')
            return 1
        return 0
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
