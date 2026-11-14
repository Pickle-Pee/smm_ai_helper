"""A supplied sample stays separate from a prospective strategic diagnosis."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import asyncpg
import httpx
from jsonschema import Draft202012Validator
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage, StatementSemanticsError
from app.module_execution.executors.cmo_source_diagnoses import (
    DIAGNOSIS_DEFINITION, DIAGNOSIS_INTROS, DIAGNOSIS_RELATIONS,
    demo_diagnosis_choices, render_source_diagnosis,
)
from app.module_execution.executors.cmo_support_wire import support_selection_catalog, decode_support_selection_wire
from app.module_execution.executors.downstream_fidelity import validate_leaf
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.service import evaluate_result
from tests.test_cmo_generation_policy import source_request, source_contracts
from tests.test_cmo_provider_contract import PRICE
from tests.test_cmo_support_wire import wire_output
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import fact


DEMO = 'Демонстрационный образец показывает сравнение снимков.'
ACTUAL_MIXED = ('Демонстрационный образец показывает сравнение снимков, что подтверждает возможность '
    'показать эффект, но не подтверждает, что аудитория видит это как ориентир практики.')


@pytest.fixture(autouse=True)
def forbid_uncontrolled_io(monkeypatch):
    original_send = httpx.AsyncClient.send

    async def send(client, *args, **kwargs):
        assert isinstance(client._transport, httpx.MockTransport), 'Uncontrolled HTTP is forbidden'
        return await original_send(client, *args, **kwargs)

    def reject(*args, **kwargs):
        raise AssertionError('Database or synchronous HTTP is forbidden')

    async def reject_async(*args, **kwargs):
        raise AssertionError('Database is forbidden')

    monkeypatch.setattr(httpx.AsyncClient, 'send', send)
    monkeypatch.setattr(httpx.Client, 'send', reject)
    monkeypatch.setattr(asyncpg, 'connect', reject_async)
    monkeypatch.setattr(asyncpg, 'create_pool', reject)
    monkeypatch.setattr(Engine, 'connect', reject)
    monkeypatch.setattr(AsyncEngine, 'connect', reject)


def prepared(req, relation=None):
    canonical, schema, ids, parents, numeric, sources = source_contracts(req)
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents), sources)
    if relation is not None:
        value['outputs']['strategic_diagnosis']['items'][0]['diagnostic_relation'] = relation
    return canonical, schema, ids, parents, numeric, sources, value


def test_actual_mixed_demo_diagnosis_cannot_be_generated_as_unbound_prose():
    req = source_request('existing_proof', DEMO, names=('strategic_diagnosis',))
    _, schema, ids, parents, _, sources = source_contracts(req)
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents), sources)
    value['outputs']['strategic_diagnosis']['items'] = [ACTUAL_MIXED]
    assert not Draft202012Validator(schema).is_valid(value)


@pytest.mark.parametrize('relation', DIAGNOSIS_RELATIONS)
@pytest.mark.parametrize('full', [False, True])
def test_complete_demo_and_prospective_gap_pass_normal_executor_quality_and_v1_history(relation, full):
    req = source_request('existing_proof', DEMO, names=None if full else ('strategic_diagnosis', 'strategic_priorities'))
    observed = []

    async def model(**kwargs):
        *_, sources, value = prepared(req, relation)
        assert Draft202012Validator(kwargs['response_schema']).is_valid(value)
        observed.append(deepcopy(value))
        return json.dumps(value)

    result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    row = next(row for row in result.payload['outputs'] if row['output_name'] == 'strategic_diagnosis')
    assert row['items'] == (DEMO, DIAGNOSIS_RELATIONS[relation])
    assert row['text'] == DIAGNOSIS_INTROS[0] and row['kind'] == 'HYPOTHESIS' and row['confidence'] == 'UNKNOWN'
    assert len(row['evidence_ids']) == 1 and row['parent_claim_ids']
    assert all(not flag for flag in observed[0]['outputs']['strategic_diagnosis']['additional_evidence_support'].values())
    assert all(row['evidence_ids'][0] not in other['evidence_ids'] for other in result.payload['outputs']
               if other['output_name'] != 'strategic_diagnosis')
    assert len(result.payload['outputs']) == (9 if full else 2)
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
    assert result_from_json(result_to_json(result)) == result


@pytest.mark.parametrize('flag', [False, True])
def test_recipe_binds_selected_demo_same_output_and_overlap_is_one_citation(flag):
    req = source_request('existing_proof', DEMO, names=('strategic_diagnosis', 'strategic_priorities'))
    canonical, schema, ids, parents, numeric, sources, value = prepared(req)
    marker, source = next(iter(demo_diagnosis_choices(sources).items()))
    value['outputs']['strategic_diagnosis']['additional_evidence_support'][source['evidence_key']] = flag
    value['outputs']['strategic_priorities']['items'] = [marker]
    before = deepcopy(value)
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert value == before and Draft202012Validator(schema).is_valid(value)
    diagnosis, priority = decoded['outputs']
    assert diagnosis['items'][0] == priority['items'][0] == DEMO
    assert diagnosis['evidence_ids'] == priority['evidence_ids'] == [source['evidence_id']]
    # Each output receives a citation from its own explicit selector; the priority
    # source choice neither witnesses nor repairs arbitrary diagnosis prose.
    value['outputs']['strategic_diagnosis']['items'] = [ACTUAL_MIXED]
    assert not Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)


@pytest.mark.parametrize('change', [
    'unknown', 'parent_alias', 'parent_id', 'owner_role', 'literal', 'mixed',
    'extra', 'missing_source', 'missing_relation', 'unknown_relation', 'second',
    'prose_item', 'confidence', 'kind', 'intro',
])
def test_diagnosis_recipe_rejects_unbound_or_model_written_content_without_repair(change):
    req = source_request('existing_proof', DEMO, names=('strategic_diagnosis',))
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact('confirmed_business_fact', 'Owner confirms practical tasks.'))))
    canonical, schema, ids, parents, numeric, sources, value = prepared(req)
    row = value['outputs']['strategic_diagnosis']
    recipe = row['items'][0]
    if change == 'unknown': recipe['source_choice'] = 'SOURCE:e999'
    elif change == 'parent_alias': recipe['source_choice'] = next(iter(support_selection_catalog(ids, parents)['parents']))
    elif change == 'parent_id': recipe['source_choice'] = next(iter(parents))
    elif change == 'owner_role': recipe['source_choice'] = next(k for k, s in sources.items() if s['input_key'] == 'confirmed_business_fact')
    elif change == 'literal': recipe['source_choice'] = DEMO
    elif change == 'mixed': recipe['source_choice'] += ' plus positive interpretation'
    elif change == 'extra': recipe['assertion'] = 'The demonstration proves the course works.'
    elif change == 'missing_source': recipe.pop('source_choice')
    elif change == 'missing_relation': recipe.pop('diagnostic_relation')
    elif change == 'unknown_relation': recipe['diagnostic_relation'] = 'The audience already values this effect.'
    elif change == 'second': row['items'].append(deepcopy(recipe))
    elif change == 'prose_item': row['items'] = [ACTUAL_MIXED]
    elif change == 'confidence': row['confidence'] = 'HIGH'
    elif change == 'kind': row['kind'] = 'RECOMMENDATION'
    else: row['text'] = 'The demo proves the course works.'
    before = deepcopy(value)
    assert not Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert value == before


@pytest.mark.parametrize('role,text', [
    ('product_truth', DEMO), ('confirmed_business_fact', DEMO), ('target_or_target_hypothesis', DEMO),
    ('existing_proof', 'A demonstration compares 2 photographs.'),
    ('existing_proof', 'A demonstration compares two photographs.'),
    ('existing_proof', 'x' * 301), ('existing_proof', 'x' * 4001),
])
def test_ineligible_sources_keep_original_diagnosis_fallback_without_truncation(role, text):
    req = source_request(role, text, names=('strategic_diagnosis',))
    _, schema, _, _, _, sources = source_contracts(req)
    assert not demo_diagnosis_choices(sources)
    assert DIAGNOSIS_DEFINITION not in schema['$defs']
    assert schema['properties']['outputs']['properties']['strategic_diagnosis'] == {'$ref': '#/$defs/OtherStrategyStatement'}
    assert all(source['text'] == text for source in sources.values() if source['input_key'] == role)


def test_only_first_party_existing_proof_can_enable_a_diagnosis_recipe():
    choices = {'SOURCE:e000': {'text': DEMO, 'evidence_id': 'evd_demo', 'evidence_key': 'e000',
        'input_key': 'existing_proof', 'source_class': 'FIRST_PARTY'}}
    assert demo_diagnosis_choices(choices) == choices
    for update in ({'input_key': 'product_truth'}, {'source_class': 'EXTERNAL_PRIMARY'}, {'text': 'x' * 301}):
        changed = deepcopy(choices)
        changed['SOURCE:e000'].update(update)
        assert demo_diagnosis_choices(changed) == {}


def test_exact_300_demo_is_preserved_and_old_v11_wire_rejects():
    req = source_request('existing_proof', 'x' * 300, names=('strategic_diagnosis',))
    canonical, schema, ids, parents, numeric, sources, value = prepared(req)
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert decoded['outputs'][0]['items'][0] == 'x' * 300
    assert all(0 < len(text) <= 300 for text in decoded['outputs'][0]['items'])
    value['wire_contract_version'] = 'virtual_cmo.support_selection.v11'
    assert not Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)


def test_partial_request_without_diagnosis_installs_no_specialization():
    req = source_request('existing_proof', DEMO, names=('strategic_priorities',))
    _, schema, _, _, _, _ = source_contracts(req)
    assert DIAGNOSIS_DEFINITION not in schema['$defs']
    assert schema['properties']['outputs']['properties']['strategic_priorities'] == {'$ref': '#/$defs/OtherStrategyStatement'}


def test_numeric_context_stays_complete_separate_and_cannot_rewrite_diagnosis_prose():
    req = source_request('existing_proof', DEMO, names=('strategic_diagnosis',))
    canonical, schema, ids, parents, numeric, sources, value = prepared(req)
    numeric_id = next(row['support_id'] for row in numeric if row['exact_quote'] == PRICE)
    row = value['outputs']['strategic_diagnosis']
    row['numeric_context'] = [{'support_id': numeric_id, 'quote': PRICE}]
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert decoded['outputs'][0]['numeric_context'] == row['numeric_context']
    assert numeric_id in decoded['outputs'][0]['evidence_ids']
    assert decoded['outputs'][0]['items'][0] == DEMO
    row['text'] = PRICE
    assert not Draft202012Validator(schema).is_valid(value)


def test_primary_without_parents_and_additional_false_still_conserve_explicit_demo():
    req = replace(source_request('existing_proof', DEMO, names=('strategic_diagnosis',)), upstream_results=())
    canonical, _, ids, parents, numeric, sources, value = prepared(req)
    source = next(iter(demo_diagnosis_choices(sources).values()))
    value['outputs']['strategic_diagnosis']['primary_evidence_key'] = source['evidence_key']
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert not decoded['outputs'][0]['parent_claim_ids']
    assert decoded['outputs'][0]['evidence_ids'] == [source['evidence_id']]


@pytest.mark.parametrize('other_count', [31, 32])
def test_recipe_selection_preserves_final_evidence_family_32_bound(other_count):
    req = source_request('existing_proof', DEMO, names=('strategic_diagnosis',))
    extras = tuple(fact('known_business_context.source_' + str(i), 'Supplied business context') for i in range(30))
    req = replace(req, context_packet=replace(req.context_packet, known_facts=(*req.context_packet.known_facts, *extras)))

    async def model(**kwargs):
        *_, sources, value = prepared(req)
        source = next(iter(demo_diagnosis_choices(sources).values()))
        flags = value['outputs']['strategic_diagnosis']['additional_evidence_support']
        others = [alias for alias in flags if alias != source['evidence_key']]
        assert len(others) >= other_count
        for alias in others[:other_count]: flags[alias] = True
        assert flags[source['evidence_key']] is False
        assert Draft202012Validator(kwargs['response_schema']).is_valid(value)
        return json.dumps(value)

    execute = VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute
    if other_count == 32:
        with pytest.raises(ExecutorOutputError): asyncio.run(execute(req))
    else:
        result = asyncio.run(execute(req))
        assert len(result.payload['outputs'][0]['evidence_ids']) == 32


@pytest.mark.parametrize('invalid', [False, True])
def test_real_http_adapter_exposes_demo_only_recipe_and_uses_one_attempt(monkeypatch, invalid):
    from app.orchestration_runtime.model_adapter import production_model_call
    req = source_request('existing_proof', DEMO)
    calls = []

    def respond(request):
        body = json.loads(request.content)
        data = json.loads(body['input'][1]['content'])
        schema = body['text']['format']['schema']
        value = wire_output(req.expected_outputs, data['support_selection_catalog'], data['cmo_source_selection_catalog'])
        assert schema['properties']['outputs']['properties']['strategic_diagnosis'] == {'$ref': '#/$defs/' + DIAGNOSIS_DEFINITION}
        assert Draft202012Validator(schema).is_valid(value)
        if invalid:
            value['outputs']['strategic_diagnosis']['items'] = [ACTUAL_MIXED]
            assert not Draft202012Validator(schema).is_valid(value)
        calls.append(body)
        return httpx.Response(200, json={'status': 'completed', 'output_text': json.dumps(value)})

    install_transport(monkeypatch, respond)
    execute = VirtualCMOExecutor(model_call=production_model_call, support_selection_wire=True).execute
    if invalid:
        with pytest.raises(ExecutorOutputError) as caught: asyncio.run(execute(req))
        assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    else:
        result = asyncio.run(execute(req))
        assert len(result.payload['outputs']) == 9
        quality = evaluate_result(req.execution_id, result, req.upstream_results)
        assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
    assert len(calls) == 1


def test_existing_guard_still_rejects_actual_mixed_leaf_even_with_selected_demo():
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(ACTUAL_MIXED, demo=(DEMO,))
    assert caught.value.rule.value == 'demonstration_assertion_requires_source'
    with pytest.raises(StatementSemanticsError):
        validate_leaf(DEMO)
    validate_leaf(DEMO, demo=(DEMO,))


def test_renderer_preserves_complete_source_and_rejects_unknown_recipe_fields():
    req = source_request('existing_proof', DEMO, names=('strategic_diagnosis',))
    *_, sources, value = prepared(req)
    recipe = value['outputs']['strategic_diagnosis']['items'][0]
    choices = demo_diagnosis_choices(sources)
    before = deepcopy(choices)
    rendered, identity = render_source_diagnosis(recipe, choices)
    assert rendered == [DEMO, DIAGNOSIS_RELATIONS[recipe['diagnostic_relation']]]
    assert identity == choices[recipe['source_choice']]['evidence_id'] and choices == before
    with pytest.raises(ModuleExecutionContractError):
        render_source_diagnosis({**recipe, 'assertion': ACTUAL_MIXED}, choices)
