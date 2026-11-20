import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
from jsonschema import Draft202012Validator
import pytest

from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors.experiments import ExperimentsExecutor, strategic_parents
from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage
from app.module_execution.executors.experiments_support_selection import (
    INTERVENTION_RECIPES, TEST_METHOD_DEFINITION, OTHER_STATEMENT_DEFINITION,
    support_selection_wire_schema,
)
from app.module_execution.executors.experiments_support_wire import (
    STATEMENT_NUMERIC_ASSERTION_DEFINITION, NUMERIC_ASSERTION_DEFINITION,
)
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.service import evaluate_result
from tests.test_experiments_support_selection import invocation, typed_payload, scope_schema
from tests.test_experiments_support_wire import replace_parent_assertion
from tests.test_variant_quantity_grounding import ACTUAL_METHOD


@pytest.mark.parametrize('recipe', INTERVENTION_RECIPES)
@pytest.mark.parametrize('partial', [False, True])
def test_complete_method_plan_preserves_normal_pipeline_and_history(invocation, recipe, partial):
    req = replace(invocation, expected_outputs=('test_method',)) if partial else invocation
    async def model(**kw):
        payload = typed_payload(json.loads(kw['text']), kw['response_schema'])
        next(r for r in payload['outputs'] if r['output_name'] == 'test_method')['text'] = recipe
        for design in payload['experiments']: design['intervention'] = recipe
        assert Draft202012Validator(kw['response_schema']).is_valid(payload)
        return json.dumps(payload)
    result = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        support_selection_wire=True).execute(req))
    assert next(r for r in result.payload['outputs'] if r['output_name'] == 'test_method')['text'] == recipe
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
    assert result_from_json(result_to_json(result)) == result


@pytest.mark.parametrize('bad', [ACTUAL_METHOD, INTERVENTION_RECIPES[0] + ' Compare two variants.',
    INTERVENTION_RECIPES[0][:-1], {'text': INTERVENTION_RECIPES[0]}])
def test_method_contract_rejects_original_count_fragments_and_appended_or_malformed_plans(invocation, bad):
    async def model(**kw):
        payload = typed_payload(json.loads(kw['text']), kw['response_schema'])
        next(r for r in payload['outputs'] if r['output_name'] == 'test_method')['text'] = bad
        assert not Draft202012Validator(kw['response_schema']).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


@pytest.mark.parametrize('cite', [False, True])
def test_long_complete_numeric_method_keeps_4000_bound_independent_of_300_design_bound(invocation, cite):
    numeric_id, other_id, *_ = strategic_parents(invocation)
    quote = ('Ask two variants. ' + 'Preserve the supplied comparison context. ' * 12).rstrip()
    assert 300 < len(quote) < 4000
    req = replace_parent_assertion(invocation, numeric_id, quote)
    async def model(**kw):
        schema = kw['response_schema']
        assert schema['$defs'][STATEMENT_NUMERIC_ASSERTION_DEFINITION]['maxLength'] == 4000
        assert quote in schema['$defs'][STATEMENT_NUMERIC_ASSERTION_DEFINITION]['enum']
        assert quote not in schema['$defs'].get(NUMERIC_ASSERTION_DEFINITION, {}).get('enum', [])
        data = json.loads(kw['text'])
        payload = typed_payload(data, schema)
        row = next(r for r in payload['outputs'] if r['output_name'] == 'test_method')
        row.update(text=quote, strategic_parent_id=other_id)
        alias = next(k for k, v in data['experiments_support_selection_catalog']['parents'].items() if v == numeric_id)
        row['additional_parent_support'][alias] = cite
        assert Draft202012Validator(schema).is_valid(payload)
        assert not Draft202012Validator(schema).is_valid({**payload, 'outputs':[
            {**r, 'text': 'Ask two variants.'} if r['output_name']=='test_method' else r for r in payload['outputs']]})
        return json.dumps(payload)
    execute = ExperimentsExecutor(model_call=model, strategic_parent_wire=True, support_selection_wire=True).execute
    if cite:
        result = asyncio.run(execute(req))
        assert next(r for r in result.payload['outputs'] if r['output_name']=='test_method')['text'] == quote
    else:
        with pytest.raises(ExecutorOutputError) as caught: asyncio.run(execute(req))
        assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_method_definition_cannot_be_spoofed_as_other_or_collide_with_canonical_schema():
    v2, evidence, parents = scope_schema(2, 3)
    schema = support_selection_wire_schema(v2, 16, evidence, parents)
    other = schema['$defs'][OTHER_STATEMENT_DEFINITION]
    assert len(other['properties']['output_name']['enum']) == 11
    assert 'test_method' not in other['properties']['output_name']['enum']
    branch = schema['$defs'][TEST_METHOD_DEFINITION]
    assert branch['properties']['text']['enum'] == list(INTERVENTION_RECIPES)
    statement = {'output_name':'mechanism', 'text':'Compare supplied alternatives', 'kind':'HYPOTHESIS',
        'confidence':'MEDIUM', 'strategic_parent_id':parents[0],
        'additional_evidence_support':{'e000':False,'e001':False},
        'additional_parent_support':{'p000':False,'p001':False,'p002':False}}
    validator = Draft202012Validator({'$defs':schema['$defs'], **schema['$defs']['ExperimentStatement']})
    assert validator.is_valid(statement)
    assert not validator.is_valid({**statement, 'output_name':'test_method'})
    collision = deepcopy(v2)
    collision['$defs'][TEST_METHOD_DEFINITION] = {'type': 'string'}
    from app.module_execution.errors import ModuleExecutionContractError
    with pytest.raises(ModuleExecutionContractError): support_selection_wire_schema(collision, 16, evidence, parents)


def test_actual_mocked_http_uses_method_recipe_without_changing_other_output_shapes(monkeypatch, invocation):
    from tests.test_graph_model_adapter import install_transport
    from app.orchestration_runtime.model_adapter import production_model_call
    calls = []
    def respond(request):
        body = json.loads(request.content)
        schema = body['text']['format']['schema']
        assert TEST_METHOD_DEFINITION in schema['$defs']
        data = json.loads(body['input'][1]['content'])
        payload = typed_payload(data, schema)
        assert Draft202012Validator(schema).is_valid(payload)
        calls.append(body)
        return httpx.Response(200, json={'status':'completed','output_text':json.dumps(payload)})
    install_transport(monkeypatch, respond)
    result = asyncio.run(ExperimentsExecutor(model_call=production_model_call, strategic_parent_wire=True,
        support_selection_wire=True).execute(invocation))
    assert len(calls)==1 and len(result.payload['outputs'])==16
    assert next(r for r in result.payload['outputs'] if r['output_name']=='test_method')['text'] in INTERVENTION_RECIPES


def test_old_raw_v7_is_rejected_without_rewrite(invocation):
    async def model(**kw):
        payload = typed_payload(json.loads(kw['text']), kw['response_schema'])
        assert Draft202012Validator(kw['response_schema']).is_valid(payload)
        payload['wire_contract_version'] = 'experiments.support_selection.v7'
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))
