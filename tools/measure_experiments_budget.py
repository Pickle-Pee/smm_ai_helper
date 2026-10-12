"""Offline output capacity and input duplication audit; never calls a provider.

Run with the repository environment plus optional tiktoken. Synthetic data only.
The counterfactual input removals are sizing estimates, not safe context changes.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tiktoken
from jsonschema import Draft202012Validator

from app.module_execution.executors.intelligence_schemas import ExperimentsOutput
from app.module_registry import ModuleId
from tests.experiments_provider import full_payload
from tests.test_module_executors import dispatch, fact, request
from tests.test_strategy_intelligence import IntelligenceModel, cmo_facts, run, upstream


def main():
    encoding = tiktoken.get_encoding("o200k_base")
    def wire(value):
        # Match BaseExecutor.generate's current serialization, including spaces.
        return json.dumps(value, ensure_ascii=False)
    def tokens(value):
        return len(encoding.encode(wire(value)))

    pos = dispatch(request(ModuleId.POSITIONING))
    cmo = run(request(ModuleId.VIRTUAL_CMO, facts=cmo_facts(), upstream=upstream(pos)))
    # Include a large authorized excerpt, as in website/brand-context requests.
    excerpt = ("Сайт сообщает о форматах посещения, организации дня и порядке знакомства. " * 120)[:8000]
    req = request(ModuleId.EXPERIMENTS, facts=(fact("product_truth", excerpt),), upstream=upstream(pos, cmo))
    capture = IntelligenceModel(use_parents=True)
    run(req, model=capture)
    call = capture.calls[0]
    data = json.loads(call["text"])
    base = full_payload(data)
    validator = Draft202012Validator(call["response_schema"])
    for factor, parent_count in ((1, 1), (1, 8), (3, 8), (3, 24), (10, 24)):
        payload = copy.deepcopy(base)
        parents = data["allowed_parent_claim_ids"][:parent_count]
        for statement in payload["outputs"]:
            statement["text"] = (statement["text"] + " ") * factor
            statement["text"] = statement["text"][:4000].strip()
            statement["parent_claim_ids"] = parents
        ExperimentsOutput.model_validate(payload)
        validator.validate(payload)
        count = tokens(payload)
        print(wire(dict(kind="output", prose_factor=factor, parents_per_output=len(parents),
            outputs=len(payload["outputs"]), designs=len(payload["experiments"]),
            max_statement_chars=max(len(s["text"]) for s in payload["outputs"]),
            visible_tokens=count, with_incident_reasoning_tokens=count + 128,
            remaining_of_16000=16000 - count - 128, characters=len(wire(payload)),
            utf8_bytes=len(wire(payload).encode("utf-8")))))

    baseline = tokens(data)
    facts_removed = copy.deepcopy(data)
    # Omit only fact values already serialized as local evidence; keep metadata.
    evidence_values = [e["value"] for e in data["local_evidence"]]
    for item in facts_removed["context"]["known_facts"]:
        if item["value"] in evidence_values:
            del item["value"]
    duplicate_text_removed = copy.deepcopy(facts_removed)
    for item in duplicate_text_removed["upstream_results"]:
        result = item["result"]
        claims = {c["declared_output_name"]: c for c in result["normalized_result"]["claims"]}
        for statement in result["payload"].get("outputs", []):
            claim_value = claims[statement["output_name"]]["value"]
            if claim_value == statement["text"]:
                del statement["text"]
            else:
                try:
                    structured = json.loads(claim_value)
                except ValueError:
                    continue
                # CMO normalized values repeat summary/items/numeric_context.
                for key, normalized_key in (("text", "summary"), ("items", "items"), ("numeric_context", "numeric_context")):
                    if key in statement and statement[key] == structured.get(normalized_key):
                        del statement[key]
    upper_bound = copy.deepcopy(facts_removed)
    for item in upper_bound["upstream_results"]:
        del item["result"]["payload"]
    print(wire(dict(kind="input", baseline_tokens=baseline,
        instruction_tokens=len(encoding.encode(call["instruction"])), schema_tokens=tokens(call["response_schema"]),
        component_tokens={k: tokens(v) for k, v in data.items()},
        known_facts_tokens=tokens(data["context"]["known_facts"]),
        fact_value_savings=baseline - tokens(facts_removed),
        fact_and_upstream_duplicate_text_savings=baseline - tokens(duplicate_text_removed),
        fact_and_entire_upstream_payload_upper_bound=baseline - tokens(upper_bound))))


if __name__ == "__main__":
    main()
