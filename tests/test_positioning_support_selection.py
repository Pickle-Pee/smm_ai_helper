"""Explicit POSITIONING source selections preserve canonical validation."""
import copy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from app.module_execution.executors.positioning_support_selection import (
    support_selection_wire_schema, decode_support_selection_wire, WIRE_VERSION,
)

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.schemas import PositioningOutput
from app.module_execution.executors.support_schema import support_response_schema
from app.module_execution.executors.positioning_observation_schema import positioning_observation_schema
from app.module_registry import ModuleRegistry, ModuleId


def fixture(names=None, parents=(), count=3):
    evidence = [SimpleNamespace(record=SimpleNamespace(evidence_id=f"evd_{i:03d}"),
        input_key="product_truth" if i == 0 else "message", value="Materials and firing included.")
        for i in range(count)]
    names = names or tuple(ModuleRegistry.load("1.3.0").get(ModuleId.POSITIONING).outputs)
    canonical = support_response_schema(PositioningOutput, [e.record.evidence_id for e in evidence], parents)
    wire = support_selection_wire_schema(canonical, PositioningOutput, names, evidence, parents)
    return canonical, wire, tuple(names), evidence, tuple(parents)


def qualitative(text):
    return {"mode": "QUALITATIVE", "value": text}


def sourced(text):
    return {"mode": "SOURCE", "value": text}


def output(f):
    canonical, wire, names, evidence, parents = f
    outputs = {}
    for name, ref in wire["properties"]["outputs"]["properties"].items():
        props = wire["$defs"][ref["$ref"].rsplit("/", 1)[-1]]["properties"]
        kind = props["kind"].get("const", props["kind"].get("enum", [None])[0])
        outputs[name] = {"text": qualitative("A direction to validate."), "kind": kind,
            "confidence": "MEDIUM", "primary_support_key": "e000",
            "evidence_support": {f"e{i:03d}": False for i in range(len(evidence))},
            "parent_support": {f"p{i:03d}": False for i in range(len(parents))}}
        if name == "RTB":
            outputs[name].pop("primary_support_key")
            outputs[name]["text"] = sourced(wire["$defs"]["AllowedPositioningRTBSourceKey"]["enum"][0])
    return {"wire_contract_version": WIRE_VERSION, "outputs": outputs, "assumptions": [], "limitations": []}


@pytest.mark.parametrize("names", [None, ("offer",), ("category", "RTB")])
@pytest.mark.parametrize("parents", [(), ("clm_a", "clm_b")])
def test_roundtrip_all_outputs_partial_and_parents(names, parents):
    f = fixture(names, parents)
    value = output(f)
    before = copy.deepcopy(value)
    decoded = decode_support_selection_wire(value, f[0], PositioningOutput, *f[2:])
    assert value == before
    assert Draft202012Validator(f[0]).is_valid(decoded)
    assert [s["output_name"] for s in decoded["outputs"]] == list(f[2])
    assert all(s["evidence_ids"] == ["evd_000"] for s in decoded["outputs"])
    assert [s["text"] for s in decoded["outputs"]] == [
        "Materials and firing included." if name == "RTB" else "A direction to validate."
        for name in f[2]
    ]
    PositioningOutput.model_validate(decoded)


def test_explicit_primary_and_additional_overlap_is_a_set_not_repaired_array():
    f = fixture(("points_of_difference",), ("clm_a",))
    value = output(f)
    row = value["outputs"]["points_of_difference"]
    row["evidence_support"].update(e000=True, e001=True)
    row["parent_support"]["p000"] = True
    decoded = decode_support_selection_wire(value, f[0], PositioningOutput, *f[2:])
    assert decoded["outputs"][0]["evidence_ids"] == ["evd_000", "evd_001"]
    assert decoded["outputs"][0]["parent_claim_ids"] == ["clm_a"]


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(evidence_ids=["evd_000", "evd_000"]),
    lambda r: r.update(parent_claim_ids=[]),
    lambda r: r.update(primary_support_key="invented"),
    lambda r: r["evidence_support"].update(e000=1),
    lambda r: r["evidence_support"].update(e000="true"),
    lambda r: r["evidence_support"].update(e000=None),
    lambda r: r["evidence_support"].update(unknown=True),
    lambda r: r["evidence_support"].pop("e000"),
    lambda r: r.pop("primary_support_key"),
    lambda r: r.update(extra="unreviewed"),
])
def test_malformed_wire_and_legacy_arrays_fail_without_repair(mutate):
    f = fixture(("offer",))
    value = output(f)
    mutate(value["outputs"]["offer"])
    before = copy.deepcopy(value)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, f[0], PositioningOutput, *f[2:])
    assert value == before


@pytest.mark.parametrize("name", ["offer", "RTB", "value_proposition", "positioning_statement"])
def test_product_primary_must_be_actual_local_truth_even_with_other_support(name):
    f = fixture((name,), ("clm_a",))
    for primary in ("e001", "p000"):
        value = output(f)
        value["outputs"][name]["primary_support_key"] = primary
        with pytest.raises(ModuleExecutionContractError):
            decode_support_selection_wire(value, f[0], PositioningOutput, *f[2:])


def test_nonproduct_parent_primary_and_additional_local_support_remain_available():
    f = fixture(("category",), ("clm_a",))
    value = output(f)
    value["outputs"]["category"]["primary_support_key"] = "p000"
    decoded = decode_support_selection_wire(value, f[0], PositioningOutput, *f[2:])
    assert decoded["outputs"][0]["evidence_ids"] == []
    assert decoded["outputs"][0]["parent_claim_ids"] == ["clm_a"]


def test_no_source_truncation_and_original_32_canonical_bound_remain():
    f = fixture(("offer",), count=40)
    value = output(f)
    assert len(value["outputs"]["offer"]["evidence_support"]) == 40
    value["outputs"]["offer"]["evidence_support"] = {f"e{i:03d}": True for i in range(40)}
    decoded = decode_support_selection_wire(value, f[0], PositioningOutput, *f[2:])
    assert len(decoded["outputs"][0]["evidence_ids"]) == 40
    assert not Draft202012Validator(f[0]).is_valid(decoded)


@pytest.mark.parametrize("mutate", [
    lambda s: s["properties"]["outputs"].update(maxItems=1),
    lambda s: s.update(unreviewed=True),
    lambda s: s["$defs"].update(Unknown={"type": "string"}),
])
def test_unknown_canonical_changes_refuse_before_provider_and_preserve_input(mutate):
    f = fixture(("offer",))
    canonical = copy.deepcopy(f[0]); mutate(canonical)
    before = copy.deepcopy(canonical)
    with pytest.raises(ModuleExecutionContractError):
        support_selection_wire_schema(canonical, PositioningOutput, *f[2:])
    assert canonical == before


def test_boolean_overhead_refuses_without_source_or_output_truncation():
    with pytest.raises(ModuleExecutionContractError):
        fixture(count=129)  # 16 * 129 exceeds the existing 2048 flag preflight.


def test_existing_provider_observation_subset_applies_to_every_keyed_output():
    f = fixture()
    narrowed = positioning_observation_schema(f[1])
    for name, ref in narrowed["properties"]["outputs"]["properties"].items():
        kind = narrowed["$defs"][ref["$ref"].rsplit("/", 1)[-1]]["properties"]["kind"]
        assert "OBSERVATION" not in kind.get("enum", [kind.get("const")])


@pytest.mark.parametrize("names", [("unknown",), ("offer", "offer")])
def test_unknown_or_duplicate_output_names_fail_closed(names):
    with pytest.raises(ModuleExecutionContractError):
        fixture(names)


class SelectionModel:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    async def __call__(self, **kwargs):
        return self.build(**kwargs)

    def build(self, **kwargs):
        import json
        self.calls.append(kwargs)
        data = json.loads(kwargs["text"])
        schema = kwargs["response_schema"]
        catalog = data["positioning_support_selection_catalog"]
        local = {e["evidence_id"]: e for e in data["local_evidence"]}
        product = next(e for e in data["local_evidence"] if e["input_key"] == "product_truth")
        primary = next(key for key, identity in catalog["evidence"].items() if identity == product["evidence_id"])
        rows = {}
        for name, ref in schema["properties"]["outputs"]["properties"].items():
            props = schema["$defs"][ref["$ref"].rsplit("/", 1)[-1]]["properties"]
            kind = props["kind"].get("const", "HYPOTHESIS")
            rows[name] = {"text": qualitative("A qualitative direction to validate."), "kind": kind,
                "confidence": "MEDIUM", "primary_support_key": primary,
                "evidence_support": {key: key == primary for key in catalog["evidence"]},
                "parent_support": {key: False for key in catalog["parents"]}}
            if name == "RTB":
                rows[name].pop("primary_support_key")
                sources = data["positioning_product_sources"]
                key = next(key for key, source in sources.items()
                           if source["evidence_id"] == product["evidence_id"])
                rows[name]["text"] = sourced(key)
        payload = {"wire_contract_version": WIRE_VERSION, "outputs": rows, "assumptions": [], "limitations": []}
        assert Draft202012Validator(schema).is_valid(payload)
        if self.mutate:
            self.mutate(payload, data)
        self.last_payload = copy.deepcopy(payload)
        return json.dumps(payload)


@pytest.mark.parametrize("job,alternative", [(True, True), (False, True), (True, False), (False, False)])
@pytest.mark.parametrize("projection", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_actual_executor_full_and_partial_seeds_projection(job, alternative, projection, partial):
    import asyncio
    from app.module_execution.executors.positioning import PositioningExecutor
    from app.orchestration_runtime.service import evaluate_result
    from app.module_execution.acceptance import fully_accepted
    from tests.test_positioning_seed_contract import seed_request
    invocation = seed_request(job, alternative, **({"outputs": ("offer",)} if partial else {}))
    model = SelectionModel()
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
        provider_schema_projection=projection).execute(invocation))
    assert len(model.calls) == 1 and len(result.normalized_result.claims) == len(invocation.expected_outputs)
    # Graph job IDs are hexadecimal; the seed helper's execution label has '-'.
    quality = evaluate_result("a" * 32, result, invocation.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert all(len(s["evidence_ids"]) == 1 for s in result.payload["outputs"])


@pytest.mark.parametrize("text", ["An experienced instructor.", "Guaranteed delivery.", "A group of 10 participants."])
def test_selection_does_not_bypass_assurance_or_numeric_semantics(text):
    import asyncio
    from app.module_execution.executors.positioning import PositioningExecutor
    from app.module_execution.executors import ExecutorOutputError
    from tests.test_module_executors import request
    model = SelectionModel(lambda p, d: p["outputs"]["offer"].update(text=qualitative(text)))
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(
            request(ModuleId.POSITIONING, outputs=("offer",))))
    assert len(model.calls) == 1


@pytest.mark.parametrize("enabled", [False, True])
def test_model_owned_duplicate_arrays_are_rejected_in_both_modes(enabled):
    import asyncio
    from app.module_execution.executors.positioning import PositioningExecutor
    from app.module_execution.executors import ExecutorOutputError
    from tests.test_module_executors import request, FakeModel
    model = FakeModel(lambda p, d: p["outputs"][0]["evidence_ids"].append(p["outputs"][0]["evidence_ids"][0]))
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=enabled).execute(
            request(ModuleId.POSITIONING, outputs=("offer",))))
    assert len(model.calls) == 1


@pytest.mark.parametrize("flag", [0, 1, "true", None])
def test_flag_is_strict_boolean(flag):
    from app.module_execution.executors.positioning import PositioningExecutor
    with pytest.raises(TypeError):
        PositioningExecutor(model_call=None, support_selection_wire=flag)


@pytest.mark.parametrize("option", ["product_support_wire", "minimal_provider_schema"])
def test_incompatible_wire_experiments_refuse(option):
    from app.module_execution.executors.positioning import PositioningExecutor
    with pytest.raises(ValueError):
        PositioningExecutor(model_call=None, support_selection_wire=True, **{option: True})


@pytest.mark.parametrize("selection", [False, True])
@pytest.mark.parametrize("projection", [False, True])
def test_default_off_registry_and_real_composition(monkeypatch, selection, projection):
    from app.config import settings, Settings
    from app.orchestration_runtime.composition import build_production_graph_runtime
    from tests.test_module_executors import analyzer
    from tests.test_production_graph_worker import queue
    monkeypatch.setattr(settings, "POSITIONING_SUPPORT_SELECTION_WIRE_ENABLED", selection)
    monkeypatch.setattr(settings, "POSITIONING_SCHEMA_PROJECTION_ENABLED", projection)
    executor = build_production_graph_runtime(queue=queue(), analyzer=analyzer()).executors.resolve("positioning.v1")
    assert executor._support_selection_wire is selection
    assert executor._provider_schema_projection is projection
    assert Settings.model_fields["POSITIONING_SUPPORT_SELECTION_WIRE_ENABLED"].default is False


def test_actual_http_adapter_decodes_keyed_wire_before_original_gates(monkeypatch):
    import asyncio
    import json
    import httpx
    from tests.test_graph_model_adapter import install_transport
    from app.orchestration_runtime.model_adapter import production_model_call
    from app.module_execution.executors.positioning import PositioningExecutor
    from tests.test_module_executors import request
    model = SelectionModel()
    def provider(req):
        body = json.loads(req.content)
        raw = model.build(instruction=body["input"][0]["content"], text=body["input"][1]["content"],
            response_schema=body["text"]["format"]["schema"])
        return httpx.Response(200, json={"status": "completed", "output_text": raw})
    install_transport(monkeypatch, provider)
    result = asyncio.run(PositioningExecutor(model_call=production_model_call,
        support_selection_wire=True, provider_schema_projection=True).execute(request(ModuleId.POSITIONING)))
    assert len(result.normalized_result.claims) == 16 and len(model.calls) == 1


def test_old_stored_canonical_payload_remains_readable():
    old = {"outputs": [{"output_name": "offer", "text": "A historical offer.", "kind": "INFERENCE",
        "confidence": "MEDIUM", "evidence_ids": ["evd_old"], "parent_claim_ids": []}],
        "assumptions": [], "limitations": []}
    assert PositioningOutput.model_validate(old).model_dump() == old


@pytest.mark.parametrize("text,select_product,truth,expected_rule", [
    ("Начинающие, которым нужен доступный формат занятий.", False,
     "Для занятий не требуется профессиональное оборудование.", None),
    ("Начинающие могут заниматься без необходимости покупать профессиональное оборудование.", True,
     "Для занятий не требуется профессиональное оборудование.", None),
    ("Начинающие могут заниматься без необходимости покупать профессиональное оборудование.", False,
     "Для занятий не требуется профессиональное оборудование.", "product_claim_requires_truth"),
    ("Начинающие могут заниматься без необходимости покупать профессиональное оборудование.", True,
     "Для занятий требуется профессиональное оборудование.", "product_claim_requires_truth"),
    ("Начинающим гарантирован результат.", True,
     "Для занятий не требуется профессиональное оборудование.", "product_assurance_support_required"),
])
def test_target_v5_requires_explicit_support_for_product_conditions(
    text, select_product, truth, expected_rule, monkeypatch,
):
    import asyncio
    from unittest.mock import Mock
    from app.module_execution.executors import ExecutorOutputError, common
    from app.module_execution.executors.positioning import PositioningExecutor
    from tests.test_module_executors import fact, request

    audience = "Начинающие, которым нужен доступный формат занятий."
    invocation = request(ModuleId.POSITIONING, outputs=("target",), facts=(
        fact("product", "Курс"),
        fact("target_or_target_hypothesis", audience),
        fact("product_truth", truth),
    ))
    selected_ids = []

    def select_sources(payload, data):
        ids = {source["input_key"]: source["evidence_id"] for source in data["local_evidence"]}
        aliases = {identity: key for key, identity in
                   data["positioning_support_selection_catalog"]["evidence"].items()}
        target = payload["outputs"]["target"]
        target.update(text=qualitative(text),
                      primary_support_key=aliases[ids["target_or_target_hypothesis"]])
        target["evidence_support"][aliases[ids["product_truth"]]] = select_product
        selected_ids.append(ids["target_or_target_hypothesis"])
        if select_product:
            selected_ids.append(ids["product_truth"])

    model = SelectionModel(select_sources)
    executor = PositioningExecutor(model_call=model, support_selection_wire=True)
    if expected_rule:
        warning = Mock()
        monkeypatch.setattr(common.log, "warning", warning)
        with pytest.raises(ExecutorOutputError) as caught:
            asyncio.run(executor.execute(invocation))
        assert caught.value.stage.value == "statement_semantics_invalid"
        warning.assert_called_once_with(
            "Module output rejected module=%s stage=%s rule=%s",
            "POSITIONING", "statement_semantics_invalid", expected_rule,
        )
    else:
        result = asyncio.run(executor.execute(invocation))
        statement, = result.payload["outputs"]
        assert statement["text"] == text
        assert set(statement["evidence_ids"]) == set(selected_ids)
    assert len(model.calls) == 1


def test_target_and_qualified_offer_use_separate_modes_and_sources():
    import asyncio

    from app.module_execution.executors.positioning import PositioningExecutor
    from tests.test_module_executors import fact, request

    audience = "Начинающие взрослые хотят улучшить свои снимки."
    offer = "Занятия ведёт профессиональный фотограф."
    invocation = request(ModuleId.POSITIONING, outputs=("target", "offer", "RTB"), facts=(
        fact("product", "Курс фотографии"),
        fact("target_or_target_hypothesis", audience),
        fact("product_truth", offer),
    ))
    expected = {}

    def separate_outputs(payload, data):
        ids = {row["input_key"]: row["evidence_id"] for row in data["local_evidence"]}
        aliases = {identity: key for key, identity in
                   data["positioning_support_selection_catalog"]["evidence"].items()}
        product_key = next(iter(data["positioning_product_sources"]))
        for name, text, source in (
            ("target", qualitative(audience), "target_or_target_hypothesis"),
            ("offer", sourced(product_key), "product_truth"),
        ):
            expected[name] = (offer if name == "offer" else text["value"], (ids[source],))
            row = payload["outputs"][name]
            row.update(text=text, primary_support_key=aliases[ids[source]],
                       evidence_support=dict.fromkeys(row["evidence_support"], False))

    model = SelectionModel(separate_outputs)
    executor = PositioningExecutor(model_call=model, support_selection_wire=True,
                                   provider_schema_projection=True)
    result = asyncio.run(executor.execute(invocation))
    instruction = model.calls[0]["instruction"]
    assert "Keep all product conditions out of target" in instruction
    assert "This applies even when the condition is sourced" in instruction
    assert "Do not\nselect or quote a product condition for target in either mode" in instruction
    assert "use SOURCE with the corresponding positioning_product_sources" in instruction
    assert "essential product condition" not in instruction
    expected["RTB"] = expected["offer"]
    assert {row["output_name"]: (row["text"], row["evidence_ids"])
            for row in result.payload["outputs"]} == expected


@pytest.mark.parametrize(("product", "condition", "example"), [
    ("Photography course", "The course lasts 6 weeks and includes written feedback.",
     "A demonstration compares two photographs."),
    ("Ceramics workshop", "Materials and firing are included; collection is later.",
     "A sample bowl demonstrates glazing."),
])
def test_claim_plan_exposes_scoped_choices_without_leaking_product_details(product, condition, example):
    import asyncio
    import json

    from app.module_execution.executors.positioning import PositioningExecutor
    from tests.test_module_executors import fact, request

    invocation = request(ModuleId.POSITIONING, outputs=("offer", "RTB", "points_of_difference"),
                         facts=(fact("product", product),
                                fact("target_or_target_hypothesis", "Interested beginners"),
                                fact("product_truth", condition), fact("existing_proof", example)))

    def choose(payload, data):
        catalog = data["positioning_product_sources"]
        truth_key = next(k for k, v in catalog.items() if v["category"] == "product_truth")
        proof_key = next(k for k, v in catalog.items() if v["category"] == "existing_proof")
        assert catalog[proof_key]["allowed_outputs"] == ["RTB"]
        assert catalog[truth_key]["authority"] == "SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"
        serialized = json.dumps(data)
        assert condition not in serialized and example not in serialized
        payload["outputs"]["offer"]["text"] = sourced(truth_key)
        payload["outputs"]["RTB"]["text"] = sourced(proof_key)

    model = SelectionModel(choose)
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(invocation))
    by_name = {row["output_name"]: row for row in result.payload["outputs"]}
    assert by_name["offer"]["text"] == condition
    assert by_name["RTB"]["text"] == example
    assert by_name["points_of_difference"]["text"] == "A qualitative direction to validate."

    schema = model.calls[0]["response_schema"]
    valid = model.last_payload
    assert Draft202012Validator(schema).is_valid(valid)
    for output_name, source_name in (("offer", "RTB"), ("points_of_difference", "offer")):
        invalid = copy.deepcopy(valid)
        invalid["outputs"][output_name]["text"] = valid["outputs"][source_name]["text"]
        assert not Draft202012Validator(schema).is_valid(invalid)
