"""CMO explicit support sets: no duplicate model arrays or implicit citations."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import AsyncMock, patch

import httpx
from jsonschema import Draft202012Validator
import pytest

from app.config import Settings, settings
from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage, first_party_evidence, scoped_facts, parent_claims
from app.module_execution.executors.cmo_support_wire import (
    WIRE_VERSION, support_selection_catalog, support_selection_wire_schema, decode_support_selection_wire,
    RISKS_DEFINITION, RISK_TEXT_NOTES, RISK_ITEM_NOTES, ASSUMPTION_NOTES,
    TRADEOFFS_DEFINITION, TRADEOFF_ITEM_NOTES,
)
from app.module_execution.executors.intelligence_schemas import StrategyOutput
from app.module_execution.executors.numeric_grounding import numeric_quote_catalog
from app.module_execution.executors.cmo_source_selection import source_selection_catalog
from app.module_execution.executors.support_schema import support_response_schema, SupportRequirement
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_registry import ModuleId
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.service import evaluate_result
from app.orchestration_runtime.worker import transient
from tests.test_cmo_provider_contract import invocation, PRICE, DURATION
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import analyzer, fact
from tests.test_production_graph_worker import queue
from tests.test_strategy_intelligence import positioning, upstream, IntelligenceModel


def scoped_request(parents=True, outputs=None):
    req = invocation()
    return replace(req, upstream_results=upstream(positioning()) if parents else (),
                   expected_outputs=tuple(outputs) if outputs else req.expected_outputs)


def contracts(req):
    evidence = first_party_evidence(req, scoped_facts(req))
    ids = tuple(e.record.evidence_id for e in evidence)
    parents = parent_claims(req)
    canonical = support_response_schema(StrategyOutput, ids, parents,
        requirement=VirtualCMOExecutor(model_call=None).support_requirement_for(req))
    catalog = numeric_quote_catalog({e.record.evidence_id:e for e in evidence}, parents)
    source_choices = source_selection_catalog(evidence, support_selection_catalog(ids, parents)["evidence"])
    wire = support_selection_wire_schema(canonical, req.expected_outputs, ids, parents, catalog, source_choices)
    return canonical, wire, ids, parents, catalog


def wire_output(names, choices, source_choices=None):
    parents, evidence = choices["parents"], choices["evidence"]
    value = {"wire_contract_version":WIRE_VERSION, "assumptions":[], "limitations":[],
        "outputs":{name:{"text":RISK_TEXT_NOTES[0] if name == "risks" else "Validate supplied demand",
            "items":[RISK_ITEM_NOTES[0] if name == "risks" else
                     TRADEOFF_ITEM_NOTES[0] if name == "trade_offs" else "Interview prospective customers"],
            "kind":"HYPOTHESIS", "confidence":"HIGH", "numeric_context":[],
            "primary_parent_key":next(iter(parents)) if parents else None,
            "primary_evidence_key":None if parents else next(iter(evidence)),
            "additional_parent_support":{alias:False for alias in parents},
            "additional_evidence_support":{alias:False for alias in evidence}}
            for name in names}}
    from app.module_execution.executors.cmo_source_bets import BET_INTROS, owner_bet_choices
    bets = owner_bet_choices(source_choices or {})
    if 'strategic_bets' in names and bets:
        value['outputs']['strategic_bets'].update(text=BET_INTROS[0], confidence='UNKNOWN',
            items=[{'source_choice':next(iter(bets)), 'test_relation':'audience_value_ru'}])
    from app.module_execution.executors.cmo_source_diagnoses import (
        DIAGNOSIS_INTROS, DIAGNOSIS_RELATIONS, demo_diagnosis_choices,
    )
    diagnoses = demo_diagnosis_choices(source_choices or {})
    if 'strategic_diagnosis' in names and diagnoses:
        value['outputs']['strategic_diagnosis'].update(text=DIAGNOSIS_INTROS[0], confidence='UNKNOWN',
            items=[{'source_choice':next(iter(diagnoses)), 'diagnostic_relation':next(iter(DIAGNOSIS_RELATIONS))}])
    return value


def decode(req, payload):
    canonical, _, ids, parents, catalog = contracts(req)
    evidence = first_party_evidence(req, scoped_facts(req))
    source_choices = source_selection_catalog(evidence, support_selection_catalog(ids, parents)["evidence"])
    return decode_support_selection_wire(payload, canonical, req.expected_outputs, ids, parents, catalog, source_choices)


def test_legacy_provider_allows_duplicate_arrays_but_new_wire_forbids_array_fields():
    req=scoped_request()
    canonical, wire, ids, parents, catalog=contracts(req)
    legacy=VirtualCMOExecutor(model_call=None).provider_schema_for(req,canonical)
    value={"outputs":[{"output_name":"main_growth_constraint","text":"Validate demand","items":["Interview customers"],
        "kind":"HYPOTHESIS","confidence":"MEDIUM","numeric_context":[],
        "evidence_ids":[ids[0],ids[0]],"parent_claim_ids":[next(iter(parents))]}],"assumptions":[],"limitations":[]}
    assert Draft202012Validator(legacy).is_valid(value)
    payload=wire_output(req.expected_outputs,support_selection_catalog(ids,parents))
    payload["outputs"]["main_growth_constraint"]["evidence_ids"]=[ids[0],ids[0]]
    assert not Draft202012Validator(wire).is_valid(payload)


@pytest.mark.parametrize("parents_present",[False,True])
@pytest.mark.parametrize("legacy_catalog_flag",[False,True])
def test_all_outputs_typed_citations_original_gates_and_v1_roundtrip(parents_present,legacy_catalog_flag):
    req=scoped_request(parents_present)
    calls=[]
    async def model(**kwargs):
        calls.append(deepcopy(kwargs));data=json.loads(kwargs["text"])
        assert "numeric_quote_catalog" not in data and "numeric_quote_catalog_guidance" not in data
        choices=data["support_selection_catalog"]
        payload=wire_output(req.expected_outputs,choices)
        quote_id=next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"]=="product_truth")
        first=payload["outputs"][req.expected_outputs[0]]
        if not parents_present:
            first["primary_evidence_key"]=next(alias for alias,identity in choices["evidence"].items() if identity!=quote_id)
        first["numeric_context"]=[{"support_id":quote_id,"quote":PRICE}]
        assert not any(first["additional_evidence_support"].values())
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with patch("app.module_execution.executors.virtual_cmo.bind_numeric_context_citations") as binder:
        result=asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True,
            numeric_quote_catalog_enabled=legacy_catalog_flag).execute(req))
    binder.assert_not_called()
    first=result.payload["outputs"][0]
    assert first["numeric_context"][0]["support_id"] in first["evidence_ids"]
    assert first["numeric_context"][0]["quote"]==PRICE
    assert all(s["parent_claim_ids"] if parents_present else s["evidence_ids"] for s in result.payload["outputs"])
    assert tuple(s["output_name"] for s in result.payload["outputs"])==req.expected_outputs
    assert result.schema_version=="virtual_cmo.payload.v1" and "wire_contract_version" not in result.payload
    assert result_from_json(result_to_json(result))==result
    quality=evaluate_result(req.execution_id,result,req.upstream_results)
    assert fully_accepted(result,quality["accepted_result_ids"],quality["accepted_claim_ids"])
    assert len(calls)==1


@pytest.mark.parametrize("parents_present",[False,True])
def test_primary_and_additional_true_alias_name_one_citation_without_mutating_wire(parents_present):
    req=scoped_request(parents_present)
    _, wire, ids, parents, _=contracts(req)
    choices=support_selection_catalog(ids,parents)
    payload=wire_output(req.expected_outputs,choices)
    name=req.expected_outputs[0];statement=payload["outputs"][name]
    family="parents" if parents_present else "evidence"
    primary=statement["primary_parent_key" if parents_present else "primary_evidence_key"]
    statement["additional_parent_support" if parents_present else "additional_evidence_support"][primary]=True
    before=deepcopy(payload)
    result=decode(req,payload)
    refs=result["outputs"][0]["parent_claim_ids" if parents_present else "evidence_ids"]
    assert refs==[choices[family][primary]] and payload==before
    assert Draft202012Validator(wire).is_valid(payload)


@pytest.mark.parametrize("count",[1,128])
def test_alias_bijections_keep_all_authorized_sources(count):
    evidence=[f"evd_{i:03d}" for i in range(count)]
    parents=[f"clm_{i:03d}" for i in range(count)]
    choices=support_selection_catalog(reversed(evidence),reversed(parents))
    assert list(choices["evidence"])==[f"e{i:03d}" for i in range(count)]
    assert list(choices["parents"])==[f"p{i:03d}" for i in range(count)]
    assert list(choices["evidence"].values())==sorted(evidence)
    assert list(choices["parents"].values())==sorted(parents)
    canonical=support_response_schema(StrategyOutput,evidence,parents,requirement=SupportRequirement.PARENT_REQUIRED)
    wire=support_selection_wire_schema(canonical,["main_growth_constraint"],evidence,parents,[])
    assert len(wire["$defs"]["CMOAdditionalEvidenceSupport"]["required"])==count
    assert len(wire["$defs"]["CMOAdditionalParentSupport"]["required"])==count


@pytest.mark.parametrize("evidence,parents",[([],[]),(["evd_a"],list(f"clm_{i}" for i in range(129))),
    (list(f"evd_{i}" for i in range(129)),[]),(["same"],["same"])])
def test_invalid_or_unrepresentable_source_scope_refuses(evidence,parents):
    with pytest.raises(ModuleExecutionContractError):support_selection_catalog(evidence,parents)


@pytest.mark.parametrize("mutation",[
    lambda p,s: p.update(wire_contract_version="unknown"),
    lambda p,s: p.update(extra=True),
    lambda p,s: p["outputs"].pop(next(iter(p["outputs"]))),
    lambda p,s: p["outputs"].update(unknown=deepcopy(s)),
    lambda p,s: s.update(primary_parent_key="p999"),
    lambda p,s: s.update(primary_parent_key=None),
    lambda p,s: s.update(primary_evidence_key="e000"),
    lambda p,s: s.update(extra=True),
    lambda p,s: s.pop("primary_parent_key"),
    lambda p,s: s["additional_parent_support"].pop("p000"),
    lambda p,s: s["additional_parent_support"].update(p999=True),
    lambda p,s: s["additional_parent_support"].update(p000=1),
    lambda p,s: s["additional_parent_support"].update(p000="true"),
    lambda p,s: s.update(parent_claim_ids=[]),
    lambda p,s: s.update(output_name="main_growth_constraint"),
])
def test_missing_extra_unknown_alias_and_coercive_bool_never_decode(mutation):
    req=scoped_request();_, wire, ids, parents, _=contracts(req)
    payload=wire_output(req.expected_outputs,support_selection_catalog(ids,parents))
    mutation(payload,payload["outputs"][req.expected_outputs[0]])
    saved=deepcopy(payload)
    assert not Draft202012Validator(wire).is_valid(payload)
    with pytest.raises(ModuleExecutionContractError):decode(req,payload)
    assert payload==saved


@pytest.mark.parametrize("identity_key,quote",[("duration",PRICE),("product_truth",DURATION),
    ("product_truth","20 dollars"),("unknown",PRICE)])
def test_invalid_numeric_pair_cannot_become_a_citation(identity_key,quote):
    req=scoped_request();_, wire, ids, parents, _=contracts(req)
    evidence=first_party_evidence(req,scoped_facts(req));by_key={e.input_key:e.record.evidence_id for e in evidence}
    payload=wire_output(req.expected_outputs,support_selection_catalog(ids,parents))
    payload["outputs"][req.expected_outputs[0]]["numeric_context"]=[{"support_id":by_key.get(identity_key,"evd_unknown"),"quote":quote}]
    assert not Draft202012Validator(wire).is_valid(payload)
    with pytest.raises(ModuleExecutionContractError):decode(req,payload)


@pytest.mark.parametrize("names",[("risks",),("risks","main_growth_constraint")])
def test_partial_expected_outputs_define_exact_keys_and_canonical_order(names):
    req=scoped_request(outputs=names);canonical,wire,ids,parents,_=contracts(req)
    payload=wire_output(names,support_selection_catalog(ids,parents))
    payload["outputs"]=dict(reversed(tuple(payload["outputs"].items())))
    decoded=decode(req,payload)
    assert tuple(s["output_name"] for s in decoded["outputs"])==names
    assert Draft202012Validator(canonical).is_valid(decoded)
    assert set(wire["properties"]["outputs"]["required"])==set(names)


def test_thirty_three_explicit_sources_fail_original_canonical_bound_without_truncation():
    req=scoped_request(False)
    extra=tuple(fact(f"support_{i}","Qualitative source") for i in range(33))
    req=replace(req,context_packet=replace(req.context_packet,known_facts=(*req.context_packet.known_facts,*extra)))
    async def model(**kwargs):
        data=json.loads(kwargs["text"]);choices=data["support_selection_catalog"]
        payload=wire_output(req.expected_outputs,choices)
        first=payload["outputs"][req.expected_outputs[0]]
        chosen=list(choices["evidence"])[:33]
        first["primary_evidence_key"]=chosen[0]
        for alias in chosen:first["additional_evidence_support"][alias]=True
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        decoded=decode(req,payload)
        assert len(decoded["outputs"][0]["evidence_ids"])==33
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_legacy_uncited_numeric_pair_is_still_rejected():
    req=scoped_request(False)
    async def model(**kwargs):
        result=json.loads(await IntelligenceModel()(**kwargs));data=json.loads(kwargs["text"])
        by_key={e["input_key"]:e["evidence_id"] for e in data["local_evidence"]}
        result["outputs"][0].update(evidence_ids=[by_key["product"]],numeric_context=[{"support_id":by_key["product_truth"],"quote":PRICE}])
        return json.dumps(result)
    with pytest.raises(ExecutorOutputError) as caught:asyncio.run(VirtualCMOExecutor(model_call=model).execute(req))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize("field",["text","items"])
@pytest.mark.parametrize("text,provider_valid",[("Compare 2 choices",False),("Compare \u0662 choices",True)])
def test_prose_patterns_and_unicode_server_guard_remain_authoritative(field,text,provider_valid):
    req=scoped_request()
    async def model(**kwargs):
        payload=wire_output(req.expected_outputs,json.loads(kwargs["text"])["support_selection_catalog"])
        payload["outputs"][req.expected_outputs[0]][field]=[text] if field=="items" else text
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload) is provider_valid
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    assert caught.value.stage is (OutputFailureStage.STATEMENT_SEMANTICS_INVALID if provider_valid else OutputFailureStage.SCHEMA_INVALID)


@pytest.mark.parametrize("value",[None,1,"true"])
def test_constructor_requires_actual_boolean(value):
    with pytest.raises(TypeError):VirtualCMOExecutor(model_call=AsyncMock(),support_selection_wire=value)


@pytest.mark.parametrize("enabled",[False,True])
def test_default_off_configuration_and_shared_registry_wiring(monkeypatch,enabled):
    monkeypatch.setattr(settings,"VIRTUAL_CMO_SUPPORT_SELECTION_WIRE_ENABLED",enabled)
    runtime=build_production_graph_runtime(queue=queue(),analyzer=analyzer())
    assert runtime.executors.resolve("virtual_cmo.v1")._support_selection_wire is enabled
    assert Settings.model_fields["VIRTUAL_CMO_SUPPORT_SELECTION_WIRE_ENABLED"].default is False
    assert VirtualCMOExecutor(model_call=None).instruction==VirtualCMOExecutor.instruction
    assert WIRE_VERSION not in VirtualCMOExecutor.instruction
    assert WIRE_VERSION in VirtualCMOExecutor(model_call=None,support_selection_wire=True).instruction


def test_provider_mutation_cannot_weaken_wire_or_original_validation():
    req=scoped_request()
    async def model(**kwargs):
        payload=wire_output(req.expected_outputs,json.loads(kwargs["text"])["support_selection_catalog"])
        kwargs["response_schema"].clear()
        payload["outputs"][req.expected_outputs[0]]["text"]=""
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_too_many_sources_refuse_before_model():
    req=scoped_request(False)
    req=replace(req,context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts,*(fact(f"source_{i}","Qualitative value") for i in range(129)))))
    model=AsyncMock()
    with pytest.raises(ModuleExecutionContractError):
        asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    model.assert_not_called()


def test_unknown_reference_and_complete_wire_budget_refuse_without_mutation():
    req=scoped_request();canonical,_,ids,parents,catalog=contracts(req)
    canonical["$defs"]["OtherStrategyStatement"]["properties"]["text"]={"$ref":"https://outside.invalid/"}
    saved=deepcopy(canonical)
    with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(canonical,req.expected_outputs,ids,parents,catalog)
    assert canonical==saved
    # Raise the pre-wire schema close to the shared enum budget. Primary-key
    # enums and the wire version must still be checked after installation.
    ids=["evd_a","evd_b"];parents=[f"clm_{i}" for i in range(16)]
    canonical=support_response_schema(StrategyOutput,ids,parents,requirement=SupportRequirement.PARENT_REQUIRED)
    canonical["$defs"]["BudgetLiteral"]={"type":"string","enum":[str(i) for i in range(940)]}
    from app.module_execution.executors.cmo_provider_contract import cmo_provider_schema
    cmo_provider_schema(canonical,[])
    saved=deepcopy(canonical)
    with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(canonical,["main_growth_constraint"],ids,parents,[])
    assert canonical==saved


@pytest.mark.parametrize("duplicate_json",[False,True])
def test_actual_http_adapter_and_duplicate_json_key_rejection(monkeypatch,duplicate_json):
    req=scoped_request();calls=[]
    def respond(wire):
        body=json.loads(wire.content);calls.append(body)
        data=json.loads(body["input"][1]["content"])
        payload=wire_output(req.expected_outputs,data["support_selection_catalog"])
        raw=json.dumps(payload)
        if duplicate_json:raw=raw.replace('"additional_parent_support": {"p000": false}',
            '"additional_parent_support": {"p000": false, "p000": true}',1)
        return httpx.Response(200,json={"status":"completed","output_text":raw})
    install_transport(monkeypatch,respond)
    from app.orchestration_runtime.model_adapter import production_model_call
    executor=VirtualCMOExecutor(model_call=production_model_call,support_selection_wire=True)
    if duplicate_json:
        with pytest.raises(ExecutorOutputError) as caught:asyncio.run(executor.execute(req))
        assert caught.value.stage is OutputFailureStage.JSON_INVALID and not transient(caught.value)
    else:
        result=asyncio.run(executor.execute(req))
        quality=evaluate_result(req.execution_id,result,req.upstream_results)
        assert fully_accepted(result,quality["accepted_result_ids"],quality["accepted_claim_ids"])
    assert len(calls)==1 and calls[0]["max_output_tokens"]==16000


def test_numeric_context_parent_pair_is_an_explicit_additional_parent_citation():
    from tests.test_module_executors import request, facts_for_module, FakeModel, dispatch
    def quote_output(raw,data):
        raw["outputs"][1]["text"]=PRICE
    facts=tuple(replace(f,value=PRICE) if f.label=="product_truth" else f for f in facts_for_module(ModuleId.POSITIONING))
    parent=dispatch(request(ModuleId.POSITIONING,facts=facts,outputs=("differentiation","offer"),identity="numeric_positioning"),FakeModel(quote_output))
    req=replace(invocation(),upstream_results=upstream(parent))
    numeric_id=parent.normalized_result.claims[1].claim_id
    async def model(**kwargs):
        data=json.loads(kwargs["text"]);choices=data["support_selection_catalog"]
        payload=wire_output(req.expected_outputs,choices)
        first=payload["outputs"][req.expected_outputs[0]]
        first["primary_parent_key"]=next(alias for alias,identity in choices["parents"].items() if identity!=numeric_id)
        first["numeric_context"]=[{"support_id":numeric_id,"quote":PRICE}]
        assert not any(first["additional_parent_support"].values())
        return json.dumps(payload)
    result=asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    assert numeric_id in result.payload["outputs"][0]["parent_claim_ids"]
    assert len(result.payload["outputs"][0]["parent_claim_ids"])==2
    assert json.loads(result.normalized_result.claims[0].value)["numeric_context"][0]["attribution"]=="parent_claim"


def test_context_selected_source_participates_in_confidence_and_attribution():
    req=scoped_request()
    facts=tuple(replace(f,confidence=0.2) if f.label=="product_truth" else f for f in req.context_packet.known_facts)
    req=replace(req,context_packet=replace(req.context_packet,known_facts=facts))
    async def model(**kwargs):
        data=json.loads(kwargs["text"])
        payload=wire_output(req.expected_outputs,data["support_selection_catalog"])
        identity=next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"]=="product_truth")
        payload["outputs"][req.expected_outputs[0]]["numeric_context"]=[{"support_id":identity,"quote":PRICE}]
        return json.dumps(payload)
    result=asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    claim=result.normalized_result.claims[0]
    assert claim.confidence.value=="LOW"
    assert json.loads(claim.value)["numeric_context"][0]["attribution"]=="supplied_context"


def test_missing_business_context_is_still_blocked_without_model():
    req=invocation();req=replace(req,context_packet=replace(req.context_packet,known_facts=()))
    model=AsyncMock()
    result=asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    assert result.normalized_result.module_status.value=="BLOCKED"
    model.assert_not_called()


def test_decoder_does_not_consume_generator_scope_before_validation():
    req=scoped_request();canonical,_,ids,parents,catalog=contracts(req)
    payload=wire_output(req.expected_outputs,support_selection_catalog(ids,parents))
    result=decode_support_selection_wire(payload,canonical,req.expected_outputs,
        (identity for identity in ids),(identity for identity in parents),catalog)
    assert Draft202012Validator(canonical).is_valid(result)


def test_risk_policy_only_changes_risks_prose_and_assumption_items():
    req=scoped_request();canonical,wire,ids,parents,catalog=contracts(req)
    risk=wire['$defs'][RISKS_DEFINITION]
    other=wire['$defs']['OtherStrategyStatement']
    assert risk['required']==other['required'] and risk['additionalProperties'] is False
    for name,value in other['properties'].items():
        if name not in {'text','items'}:
            assert risk['properties'][name]==value
    assert risk['properties']['text']['minLength']==1
    assert risk['properties']['text']['maxLength']==4000
    assert risk['properties']['items']['minItems']==1
    assert risk['properties']['items']['maxItems']==3
    assert risk['properties']['items']['items']['maxLength']==300
    assert risk['properties']['text']['enum']==list(RISK_TEXT_NOTES)
    assert risk['properties']['items']['items']['enum']==list(RISK_ITEM_NOTES)
    assert wire['properties']['outputs']['properties']['risks']=={'$ref':'#/$defs/'+RISKS_DEFINITION}
    from app.module_execution.executors.cmo_provider_contract import QUALITATIVE_PATTERN
    for name in req.expected_outputs:
        if name=='risks':continue
        definition=('MainGrowthConstraintStatement' if name=='main_growth_constraint' else
                    TRADEOFFS_DEFINITION if name=='trade_offs' else 'OtherStrategyStatement')
        assert wire['properties']['outputs']['properties'][name]=={'$ref':'#/$defs/'+definition}
        props=wire['$defs'][definition]['properties']
        assert props['text']['pattern']==QUALITATIVE_PATTERN
        if name=='trade_offs':
            assert props['items']['items']['enum']==list(TRADEOFF_ITEM_NOTES)
        else:
            assert props['items']['items']['pattern']==QUALITATIVE_PATTERN
    original=canonical['properties']['assumptions']
    projected=wire['properties']['assumptions']
    assert {k:v for k,v in projected.items() if k!='items'}=={k:v for k,v in original.items() if k!='items'}
    assert projected['items']['enum']==list(ASSUMPTION_NOTES)


@pytest.mark.parametrize('language',[0,1])
def test_closed_risk_and_validation_assumptions_preserve_citations_context_and_gates(language):
    req=scoped_request()
    req=replace(req,context_packet=replace(req.context_packet,known_facts=(*req.context_packet.known_facts,
        fact('economics','Owner economic inputs supplied.'),fact('market_research','Competitor descriptions supplied.'))))
    async def model(**kwargs):
        data=json.loads(kwargs['text'])
        payload=wire_output(req.expected_outputs,data['support_selection_catalog'])
        risk=payload['outputs']['risks']
        risk['text']=RISK_TEXT_NOTES[language]
        risk['items']=[RISK_ITEM_NOTES[language*3]]
        identity=next(item['evidence_id'] for item in data['local_evidence'] if item['input_key']=='product_truth')
        risk['numeric_context']=[{'support_id':identity,'quote':PRICE}]
        payload['assumptions']=[ASSUMPTION_NOTES[language]]
        assert Draft202012Validator(kwargs['response_schema']).is_valid(payload)
        return json.dumps(payload)
    result=asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    risk=next(row for row in result.payload['outputs'] if row['output_name']=='risks')
    assert risk['text']==RISK_TEXT_NOTES[language]
    assert risk['numeric_context'][0]['support_id'] in risk['evidence_ids']
    assert risk['numeric_context'][0]['quote']==PRICE
    assert tuple(result.payload['assumptions'])==(ASSUMPTION_NOTES[language],)
    quality=evaluate_result(req.execution_id,result,req.upstream_results)
    assert fully_accepted(result,quality['accepted_result_ids'],quality['accepted_claim_ids'])
    assert result_from_json(result_to_json(result))==result


@pytest.mark.parametrize('location,text',[
    ('risk_text','Основные риски связаны с операционной неплатформенностью процесса обратной связи.'),
    ('risk_item','Риск несоответствия: аудитория ожидает персонального разбора вместо стандартизированной письменной обратной связи.'),
    ('risk_item','Our standardized feedback replaces personal review.'),
    ('assumption','Экономика проекта и ресурсы на обратную связь достаточны для воспроизводимого формата курса.'),
    ('assumption','Нет существенных конкурентных предложений с аналогичным сочетанием доказанной ценности.'),
    ('assumption','Аудитория понимает и ценит разницу между практическими заданиями и обычными советами.'),
    ('assumption',{'text':ASSUMPTION_NOTES[0]}),
])
def test_risk_and_assumption_policies_do_not_generate_unsupported_factual_premises(location,text):
    req=scoped_request();calls=[]
    async def model(**kwargs):
        calls.append(True)
        payload=wire_output(req.expected_outputs,json.loads(kwargs['text'])['support_selection_catalog'])
        if location=='risk_text':payload['outputs']['risks']['text']=text
        elif location=='risk_item':payload['outputs']['risks']['items']=[text]
        else:payload['assumptions']=[text]
        assert not Draft202012Validator(kwargs['response_schema']).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model,support_selection_wire=True).execute(req))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID and calls==[True]


@pytest.mark.parametrize('mutation',['risk_collision','assumption_max','assumption_min','assumption_text_bound','assumption_existing_enum','risk_name'])
def test_unknown_risk_or_assumption_contract_refuses_without_mutation(mutation):
    req=scoped_request();canonical,_,ids,parents,catalog=contracts(req)
    if mutation=='risk_collision':canonical['$defs'][RISKS_DEFINITION]={'type':'string'}
    elif mutation=='assumption_max':canonical['properties']['assumptions']['maxItems']=13
    elif mutation=='assumption_min':canonical['properties']['assumptions']['minItems']=1
    elif mutation=='assumption_text_bound':canonical['properties']['assumptions']['items']['maxLength']=3999
    elif mutation=='assumption_existing_enum':canonical['properties']['assumptions']['items']['enum']=['unexpected']
    else:canonical['$defs']['OtherStrategyStatement']['properties']['output_name']['enum'].remove('risks')
    before=deepcopy(canonical)
    with pytest.raises(ModuleExecutionContractError):
        support_selection_wire_schema(canonical,req.expected_outputs,ids,parents,catalog)
    assert canonical==before
