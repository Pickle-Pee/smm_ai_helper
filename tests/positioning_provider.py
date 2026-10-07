"""Synthetic provider double: selective support and the observed USP kind choice.

No live response or business data is retained. The proposed RECOMMENDATION for
USP_directions reproduces the diagnosed class; strict generation must exclude it.
"""
import json

import httpx


ROWS = (
    ("category", "INFERENCE", "product"),
    ("frame_of_reference", "INFERENCE", "relevant_alternative"),
    ("target", "OBSERVATION", "target_or_target_hypothesis"),
    ("demand_context", "INFERENCE", "customer_job_or_need"),
    ("JTBD_frame", "INFERENCE", "customer_job_or_need"),
    ("value_proposition", "HYPOTHESIS", "product_truth"),
    ("differentiation", "HYPOTHESIS", "product_truth"),
    ("points_of_parity", "INFERENCE", "relevant_alternative"),
    ("points_of_difference", "HYPOTHESIS", "product_truth"),
    ("RTB", "OBSERVATION", "product_truth"),
    ("positioning_statement", "HYPOTHESIS", "product_truth"),
    ("USP_directions", "RECOMMENDATION", "product_truth"),
    ("offer", "RECOMMENDATION", "product_truth"),
    ("message_hierarchy", "RECOMMENDATION", "customer_job_or_need"),
    ("claim_risks", "INFERENCE", "product_truth"),
    ("validation_plan.", "RECOMMENDATION", "customer_job_or_need"),
)


def allowed_kinds(schema, name):
    items = schema["properties"]["outputs"]["items"]
    kinds = set()
    for variant in items.get("anyOf", [items]):
        definition = schema["$defs"][variant["$ref"].rsplit("/", 1)[-1]]
        properties = definition["properties"]
        if name in properties["output_name"]["enum"]:
            kind = properties["kind"]
            kinds.update(kind["enum"] if "enum" in kind else [kind["const"]])
    return kinds


class PositioningProvider:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append(body)
        data = json.loads(body["input"][1]["content"])
        schema = body["text"]["format"]["schema"]
        assert body["text"]["format"]["strict"] is True
        evidence = {e["input_key"]: e["evidence_id"] for e in data["local_evidence"]}
        outputs = []
        for name, proposed_kind, input_key in ROWS:
            if name not in data["expected_outputs"]:
                continue
            permitted = allowed_kinds(schema, name)
            kind = proposed_kind if proposed_kind in permitted else "HYPOTHESIS"
            assert kind in permitted
            support_key = input_key if input_key in evidence else "product_truth"
            outputs.append(dict(output_name=name, kind=kind, confidence="MEDIUM",
                text="Synthetic supported finding for " + name,
                evidence_ids=[evidence[support_key]], parent_claim_ids=[]))
        payload = dict(outputs=outputs, assumptions=[], limitations=[])
        if self.mutate:
            self.mutate(payload, data)
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(payload)})
