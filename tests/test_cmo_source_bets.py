import asyncio
from copy import deepcopy
import json
import httpx
from dataclasses import replace

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.cmo_source_bets import BET_DEFINITION, BET_INTROS, BET_RELATIONS, owner_bet_choices
from app.module_execution.executors.cmo_support_wire import support_selection_catalog, decode_support_selection_wire
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_execution.executors.common import ExecutorOutputError
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.service import evaluate_result
from tests.test_cmo_generation_policy import source_request, source_contracts
from tests.test_cmo_support_wire import owner_terms_for, wire_output
from tests.test_module_executors import fact


@pytest.fixture(autouse=True)
def wire_mechanics_in_both_languages(monkeypatch):
    # These tests exercise bet mechanics with English and Russian fixtures against the provider
    # schema. The request-language projection (tests/test_provider_language.py) would narrow a
    # Russian request to Russian generation, so it is switched off here.
    from app.module_execution.executors import provider_language
    monkeypatch.setattr(provider_language, "request_language", lambda request: None)


OWNER = ('Участники выполняют практические задания и получают письменную обратную связь. '
         'Для занятий не требуется профессиональное оборудование.')


def prepared(req, relation='audience_value_ru'):
    canonical, schema, ids, parents, numeric, sources = source_contracts(req)
    choices = owner_bet_choices(sources)
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    row = value['outputs']['strategic_bets']
    row.update(text=BET_INTROS[0], confidence='UNKNOWN', kind='HYPOTHESIS',
               items=[{'source_choice': next(iter(choices)), 'test_relation': relation}])
    return canonical, schema, ids, parents, numeric, sources, value


@pytest.mark.parametrize('role', ['product_truth', 'confirmed_business_fact'])
@pytest.mark.parametrize('relation', BET_RELATIONS)
def test_explicit_owner_bet_renders_complete_terms_and_observable_hypothesis_with_normal_gates(role, relation):
    req = source_request(role, OWNER, names=('strategic_bets', 'strategic_priorities'))
    observed = []
    async def model(**kwargs):
        *_, value = prepared(req, relation)
        assert Draft202012Validator(kwargs['response_schema']).is_valid(value)
        observed.append(deepcopy(value))
        return json.dumps(value)
    result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    bet, priority = result.payload['outputs']
    assert bet['items'] == (OWNER, BET_RELATIONS[relation])
    assert bet['confidence'] == 'UNKNOWN' and bet['kind'] == 'HYPOTHESIS'
    assert len(bet['evidence_ids']) == 1 and not priority['evidence_ids']
    assert bet['parent_claim_ids'] and priority['parent_claim_ids']
    assert all(not v for v in observed[0]['outputs']['strategic_bets']['additional_evidence_support'].values())
    assert observed[0]['outputs']['strategic_bets']['primary_evidence_key'] is None
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
    assert result_from_json(result_to_json(result)) == result


@pytest.mark.parametrize('change', ['unknown', 'parent', 'extra', 'missing', 'prose', 'second', 'confidence', 'result'])
def test_source_bet_rejects_unselected_foreign_or_model_written_recipe_content(change):
    req = source_request('product_truth', OWNER, names=('strategic_bets',))
    canonical, schema, ids, parents, numeric, sources, value = prepared(req)
    row = value['outputs']['strategic_bets']
    recipe = row['items'][0]
    if change == 'unknown': recipe['source_choice'] = 'SOURCE:e999'
    elif change == 'parent': recipe['source_choice'] = next(iter(support_selection_catalog(ids, parents)['parents']))
    elif change == 'extra': recipe['assertion'] = 'The course guarantees success.'
    elif change == 'missing': recipe.pop('source_choice')
    elif change == 'prose': row['items'] = ['Learning without equipment resonates more.']
    elif change == 'second': row['items'].append(deepcopy(recipe))
    elif change == 'confidence': row['confidence'] = 'HIGH'
    elif change == 'result': recipe['test_relation'] = 'The audience already prefers it.'
    assert not Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)


@pytest.mark.parametrize('role,text', [
    ('existing_proof', 'Демонстрационный образец показывает сравнение снимков.'),
    ('existing_proof', 'Образец показывает 3 вида хлеба за 2 дня.'),
    ('target_or_target_hypothesis', OWNER),
    ('target_or_target_hypothesis', 'Жители района от 25 до 40 лет.'),
    ('product_truth', 'x' * 301),
    ('product_truth', 'Заказ до 18:00. ' + 'x' * 290),
])
def test_ineligible_source_does_not_create_owner_bet_authority(role, text):
    req = source_request(role, text, names=('strategic_bets',))
    _, schema, _, _, _, sources = source_contracts(req)
    choices = owner_bet_choices(sources, owner_terms_for(req))
    assert all(row['text'] != text for row in choices.values())
    if not choices:
        assert BET_DEFINITION not in schema['$defs']
        assert schema['properties']['outputs']['properties']['strategic_bets'] == {'$ref': '#/$defs/OtherStrategyStatement'}


def test_parent_selection_and_exact_two_item_bound_remain_required():
    req = source_request('product_truth', OWNER, names=('strategic_bets',))
    canonical, schema, ids, parents, numeric, sources, value = prepared(req)
    original = deepcopy(value)
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert value == original
    assert decoded['outputs'][0]['items'] == [OWNER, BET_RELATIONS['audience_value_ru']]
    assert all(0 < len(t) <= 300 for t in decoded['outputs'][0]['items'])
    value['outputs']['strategic_bets']['primary_parent_key'] = None
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)


def test_partial_request_without_bets_installs_no_recipe_and_retains_original_output():
    req = source_request('product_truth', OWNER, names=('strategic_priorities',))
    _, schema, _, _, _, _ = source_contracts(req)
    assert BET_DEFINITION not in schema['$defs']
    assert schema['properties']['outputs']['properties']['strategic_priorities'] == {'$ref': '#/$defs/OtherStrategyStatement'}


def test_exact_300_character_owner_is_rendered_without_truncation_and_v10_wire_is_rejected():
    req = source_request('product_truth', 'x' * 300, names=('strategic_bets',))
    canonical, _, ids, parents, numeric, sources, value = prepared(req)
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert decoded['outputs'][0]['items'][0] == 'x' * 300
    value['wire_contract_version'] = 'virtual_cmo.support_selection.v10'
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)


def test_owner_primary_without_parents_and_demo_cannot_replace_recipe_owner():
    req = source_request('product_truth', OWNER, names=('strategic_bets',))
    req = replace(req, upstream_results=(), context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact('existing_proof', 'A demonstration sample shows a comparison.'))))
    canonical, schema, ids, parents, numeric, sources, value = prepared(req)
    row = value['outputs']['strategic_bets']
    row['primary_evidence_key'] = next(r['evidence_key'] for r in sources.values() if r['input_key'] == 'product_truth')
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)
    assert not decoded['outputs'][0]['parent_claim_ids']
    assert decoded['outputs'][0]['items'][0] == OWNER
    row['items'][0]['source_choice'] = next(k for k, r in sources.items() if r['input_key'] == 'existing_proof')
    assert not Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources)


def test_real_http_adapter_exposes_owner_only_recipe_and_retains_other_outputs(monkeypatch):
    from tests.test_graph_model_adapter import install_transport
    from app.orchestration_runtime.model_adapter import production_model_call
    req = source_request('product_truth', OWNER)
    calls = []
    def respond(request):
        body = json.loads(request.content)
        data = json.loads(body['input'][1]['content'])
        schema = body['text']['format']['schema']
        value = wire_output(req.expected_outputs, data['support_selection_catalog'], data['cmo_source_selection_catalog'], owner_terms=data.get("cmo_owner_terms_catalog"))
        assert schema['properties']['outputs']['properties']['strategic_bets'] == {'$ref': '#/$defs/' + BET_DEFINITION}
        assert schema['properties']['outputs']['properties']['strategic_priorities'] == {'$ref': '#/$defs/OtherStrategyStatement'}
        assert Draft202012Validator(schema).is_valid(value)
        calls.append(body)
        return httpx.Response(200, json={'status': 'completed', 'output_text': json.dumps(value)})
    install_transport(monkeypatch, respond)
    result = asyncio.run(VirtualCMOExecutor(model_call=production_model_call, support_selection_wire=True).execute(req))
    assert len(calls) == 1
    assert len(result.payload['outputs']) == 9
    bet = next(row for row in result.payload['outputs'] if row['output_name'] == 'strategic_bets')
    assert bet['items'] == (OWNER, BET_RELATIONS['audience_value_ru'])
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])


@pytest.mark.parametrize('other_count', [31, 32])
def test_recipe_selection_preserves_final_evidence_family_bound(other_count):
    req = source_request('product_truth', OWNER, names=('strategic_bets',))
    extra = tuple(fact('known_business_context.source_' + str(i), 'Supplied business context') for i in range(30))
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, *extra)))
    async def model(**kwargs):
        *_, sources, value = prepared(req)
        owner = next(iter(owner_bet_choices(sources).values()))
        flags = value['outputs']['strategic_bets']['additional_evidence_support']
        others = [k for k in flags if k != owner['evidence_key']]
        assert len(others) >= other_count
        for key in others[:other_count]: flags[key] = True
        assert flags[owner['evidence_key']] is False
        assert Draft202012Validator(kwargs['response_schema']).is_valid(value)
        return json.dumps(value)
    execute = VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute
    if other_count == 32:
        with pytest.raises(ExecutorOutputError): asyncio.run(execute(req))
    else:
        result = asyncio.run(execute(req))
        assert len(result.payload['outputs'][0]['evidence_ids']) == 32


# Telegram-shaped owner terms: one leaf, conditions joined by ";", with a time.
TERMS = 'заказ принимается до 18:00 накануне; хлеб забирают самовывозом из пекарни в субботу утром, доставки нет.'


def terms_prepared(req, relation='audience_value_ru'):
    canonical, schema, ids, parents, numeric, sources = source_contracts(req)
    terms = owner_terms_for(req)
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents), sources, owner_terms=terms)
    marker = next(key for key in terms if key.startswith('TERMS:'))
    value['outputs']['strategic_bets']['items'] = [{'source_choice': marker, 'test_relation': relation}]
    return canonical, schema, ids, parents, numeric, sources, terms, value


@pytest.mark.parametrize('role', ['product_truth', 'confirmed_business_fact'])
@pytest.mark.parametrize('relation', BET_RELATIONS)
def test_numeric_owner_terms_bet_keeps_complete_terms_only_in_numeric_context(role, relation):
    req = source_request(role, TERMS, names=('strategic_bets', 'strategic_priorities'))

    async def model(**kwargs):
        data = json.loads(kwargs['text'])
        assert data['cmo_owner_terms_catalog']
        assert all(row['text'] != TERMS for row in data['cmo_source_selection_catalog'].values())
        value = terms_prepared(req, relation)[-1]
        assert Draft202012Validator(kwargs['response_schema']).is_valid(value)
        return json.dumps(value)

    result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    bet = next(row for row in result.payload['outputs'] if row['output_name'] == 'strategic_bets')
    assert bet['items'] == (BET_RELATIONS[relation],)
    assert not any(ch.isdigit() for ch in bet['text'] + ' '.join(bet['items']))
    context, = bet['numeric_context']
    assert context['quote'] == TERMS and context['support_id'] in bet['evidence_ids']
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
    assert result_from_json(result_to_json(result)) == result


def test_terms_catalog_holds_the_whole_leaf_never_a_clause_split_at_semicolons():
    req = source_request('product_truth', TERMS, names=('strategic_bets',))
    canonical, schema, ids, parents, numeric, sources, terms, value = terms_prepared(req)
    assert [row['text'] for row in terms.values()] == [TERMS]
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources, terms)
    bet = decoded['outputs'][0]
    assert bet['numeric_context'] == [{'support_id': next(iter(terms.values()))['evidence_id'], 'quote': TERMS}]
    for clause in TERMS.split(';'):
        assert all(clause.strip() not in item for item in bet['items'])


@pytest.mark.parametrize('change', ['prose_items', 'prose_number', 'second', 'altered_catalog', 'missing_pair'])
def test_numeric_terms_cannot_become_model_written_or_partial_numbers(change):
    req = source_request('product_truth', TERMS, names=('strategic_bets',))
    canonical, schema, ids, parents, numeric, sources, terms, value = terms_prepared(req)
    row = value['outputs']['strategic_bets']
    if change == 'prose_items':
        row['items'] = ['Заказ принимается до вечера накануне.']
    elif change == 'prose_number':
        row['items'] = ['Заказ до 18:00 удобен аудитории.']
    elif change == 'second':
        row['items'].append(deepcopy(row['items'][0]))
    elif change == 'altered_catalog':
        key = next(iter(terms))
        terms = {key: {**terms[key], 'text': 'заказ принимается до 18:00 накануне'}}
    else:
        numeric = [entry for entry in numeric if entry['exact_quote'] != TERMS]
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources, terms)


def test_model_numeric_context_for_the_same_terms_is_one_citation_not_a_duplicate():
    req = source_request('product_truth', TERMS, names=('strategic_bets',))
    canonical, schema, ids, parents, numeric, sources, terms, value = terms_prepared(req)
    identity = next(iter(terms.values()))['evidence_id']
    value['outputs']['strategic_bets']['numeric_context'] = [{'support_id': identity, 'quote': TERMS}]
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, sources, terms)
    assert decoded['outputs'][0]['numeric_context'] == [{'support_id': identity, 'quote': TERMS}]


def test_terms_bet_schema_reserves_room_for_the_server_appended_quote():
    req = source_request('product_truth', TERMS, names=('strategic_bets',))
    canonical, schema, ids, parents, numeric, sources, terms, value = terms_prepared(req)
    assert schema['$defs'][BET_DEFINITION]['properties']['numeric_context']['maxItems'] == 2
    assert schema['$defs']['OtherStrategyStatement']['properties']['numeric_context']['maxItems'] == 3
    plain = source_request('product_truth', OWNER, names=('strategic_bets',))
    _, plain_schema, *_ = source_contracts(plain)
    assert plain_schema['$defs'][BET_DEFINITION]['properties']['numeric_context']['maxItems'] == 3
