import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-api-key")
from pathlib import Path
import json
from types import SimpleNamespace
from app.module_execution.executors import PositioningExecutor
from app.module_execution.executors.common import first_party_evidence, scoped_facts, parent_claims
from app.module_execution.executors.support_schema import support_response_schema
from app.module_execution.executors.product_support import product_wire_schema
from app.module_execution.executors.provider_schema import schema_measurement, collapse_single_support_anyof, nodes
from tests.test_positioning_product_wire import invocation
from tests.test_positioning_seed_contract import STATES


def metrics(schema):
    def nesting(node, level=0):
        if "$ref" in node:
            return nesting(schema["$defs"][node["$ref"].split("/")[-1]], level)
        current = level + int(node.get("type") in {"object", "array"})
        return max([current,
            *(nesting(child, current) for child in node.get("properties", {}).values()),
            *([nesting(node["items"], current)] if "items" in node else []),
            *(nesting(child, level) for child in node.get("anyOf", []))])
    all_nodes = list(nodes(schema))
    return {**schema_measurement(schema),
        "enum_values": sum(len(n.get("enum", [])) for n in all_nodes),
        "object_properties": sum(len(n.get("properties", {})) for n in all_nodes),
        "string_characters": sum(sum(map(len, n.get("properties", {}))) +
            sum(map(len, n.get("$defs", {}))) + sum(len(x) for x in n.get("enum", []) if isinstance(x, str)) +
            (len(n["const"]) if isinstance(n.get("const"), str) else 0) for n in all_nodes),
        "expanded_nesting": nesting(schema)}


rows = []
for job, alternative in STATES:
    for profile in ("local_only", "accepted_parent", "maximum_wire_bounds"):
        req = invocation(job, alternative)
        original_evidence = first_party_evidence(req, scoped_facts(req))
        output_type = PositioningExecutor(model_call=None).output_type_for(req, original_evidence)
        evidence = original_evidence
        parents = list(parent_claims(req)) if profile == "accepted_parent" else []
        if profile == "maximum_wire_bounds":
            evidence = tuple(SimpleNamespace(input_key="product_truth", record=SimpleNamespace(
                evidence_id=f"evd_{i:0124}")) for i in range(250))
            parents = [f"clm_{i:0124}" for i in range(250)]
        server = support_response_schema(output_type, [e.record.evidence_id for e in evidence], parents)
        wire = product_wire_schema(server, evidence)
        projected = collapse_single_support_anyof(wire)
        row = {"customer_job_seed": job, "alternative_seed": alternative, "profile": profile,
               "parser_type": output_type.__name__, "local_ids": len(evidence), "parent_ids": len(parents),
               "server_v1": metrics(server), "wire_v2": metrics(wire), "projected_wire_v2": metrics(projected)}
        for name in ("server_v1", "wire_v2", "projected_wire_v2"):
            assert row[name]["enum_values"] <= 1000
            assert row[name]["string_characters"] <= 120000
            assert row[name]["object_properties"] <= 5000
            assert row[name]["expanded_nesting"] <= 10
        rows.append(row)
report = {"baseline": "0441c49e3938c962f5165adae4f96916df164e1a", "date": "2026-10-18",
          "identities": "synthetic only; execution_id=c repeated 32 times",
          "provider_post_performed": False,
          "provider_compatibility": "documented schema subset for standard non-fine-tuned models; not live certification",
          "source": "https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses",
          "bounds": {"local_ids": 250, "parent_ids": 250, "id_characters": 128,
                     "selected_product_ids": 1, "additional_product_evidence_ids": 31,
                     "normalized_local_evidence_ids": 32, "statement_parent_ids": 32,
                     "enum_values": 1000, "schema_string_characters": 120000,
                     "object_properties": 5000, "expanded_nesting": 10}, "schemas": rows}
target = Path("docs/development/positioning-product-wire-measurements.json")
target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"schemas": len(rows), "largest_wire_bytes": max(r["wire_v2"]["bytes"] for r in rows),
                  "largest_wire_enums": max(r["wire_v2"]["enum_values"] for r in rows),
                  "largest_wire_strings": max(r["wire_v2"]["string_characters"] for r in rows)}))
