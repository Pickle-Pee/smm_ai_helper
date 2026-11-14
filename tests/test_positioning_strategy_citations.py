"""The closed strategy producer cannot select RTB-only demonstration citations."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import httpx
import pytest
from jsonschema import Draft202012Validator
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors import PositioningExecutor
from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage, first_party_evidence, scoped_facts
from app.module_execution.executors.positioning_support_selection import support_selection_wire_schema
from app.module_execution.executors.schemas import PositioningWithoutSeedsOutput
from app.module_execution.executors.support_schema import support_response_schema
from app.orchestration_runtime.claim_verification import review_positioning, verification_inputs
from app.orchestration_runtime.service import evaluate_result
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import fact
from tests.test_positioning_dynamic_review import invocation as scoped_invocation, run_review, dynamic_choice, output
from tests.test_positioning_support_selection import SelectionModel, sourced


def invocation(case):
    return replace(scoped_invocation(case), execution_id='strategy_citations_test')


NON_RTB = tuple(name for name in invocation('course').expected_outputs if name != 'RTB')


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


def demo_alias(data):
    demo = next(row['evidence_id'] for row in data['local_evidence']
                if row['input_key'] == 'existing_proof')
    return next(alias for alias, identity in data['positioning_support_selection_catalog']['evidence'].items()
                if identity == demo)


def test_actual_primary_demo_with_false_additional_flag_rejects_without_repair():
    def select(payload, data):
        alias = demo_alias(data)
        row = payload['outputs']['value_proposition']
        row['primary_support_key'] = alias
        row['evidence_support'][alias] = False

    model = SelectionModel(select)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
            strategy_selection=True).execute(invocation('course')))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert len(model.calls) == 1


@pytest.mark.parametrize('name', NON_RTB)
@pytest.mark.parametrize('selection', ['primary', 'additional'])
def test_every_non_rtb_demo_selection_is_invalid(name, selection):
    def select(payload, data):
        alias = demo_alias(data)
        row = payload['outputs'][name]
        if selection == 'primary':
            row['primary_support_key'] = alias
            row['evidence_support'][alias] = False
        else:
            row['evidence_support'][alias] = True
        assert not Draft202012Validator(model.calls[-1]['response_schema']).is_valid(payload)

    model = SelectionModel(select)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
            strategy_selection=True).execute(invocation('course')))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert len(model.calls) == 1


def test_rtb_retains_demonstration_source_and_unrestricted_boolean_map():
    def select(payload, data):
        key = next(key for key, source in data['positioning_product_sources'].items()
                   if source['category'] == 'existing_proof')
        alias = demo_alias(data)
        payload['outputs']['RTB']['text'] = sourced(key)
        payload['outputs']['RTB']['evidence_support'][alias] = True
        schema = model.calls[-1]['response_schema']
        ref = schema['properties']['outputs']['properties']['RTB']['$ref'].split('/')[-1]
        map_ref = schema['$defs'][ref]['properties']['evidence_support']['$ref'].split('/')[-1]
        assert schema['$defs'][map_ref]['properties'][alias] == {'type': 'boolean'}
        assert Draft202012Validator(schema).is_valid(payload)

    model = SelectionModel(select)
    req = invocation('course')
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
        strategy_selection=True).execute(req))
    demo_id = verification_inputs(req)
    demo_id = next(identity for identity, source in demo_id.items() if source['role'] == 'demonstration')
    rtb = next(row for row in result.payload['outputs'] if row['output_name'] == 'RTB')
    assert demo_id in rtb['evidence_ids']
    assert rtb['text'] == verification_inputs(req)[demo_id]['text']
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])

    def cite_demo(report, data):
        report['reviews']['RTB']['claims'][0]['support_ids'] = [demo_id]

    decision, _ = run_review(list(result.payload['outputs']), verification_inputs(req), cite_demo)
    assert decision['status'] == 'verified', decision


def test_v9_nonstrategy_preserves_demo_primary_and_full_boolean_maps():
    def select(payload, data):
        alias = demo_alias(data)
        schema = model.calls[-1]['response_schema']
        assert payload['wire_contract_version'] == 'positioning.support_selection.v9'
        for name, ref in schema['properties']['outputs']['properties'].items():
            props = schema['$defs'][ref['$ref'].split('/')[-1]]['properties']
            map_ref = props['evidence_support']['$ref'].split('/')[-1]
            assert schema['$defs'][map_ref]['properties'][alias] == {'type': 'boolean'}
            if name != 'RTB':
                assert alias in props['primary_support_key']['enum']
        payload['outputs']['value_proposition']['primary_support_key'] = alias
        assert Draft202012Validator(schema).is_valid(payload)

    model = SelectionModel(select)
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
        strategy_selection=False).execute(invocation('course')))
    assert len(result.payload['outputs']) == 16 and len(model.calls) == 1


def test_no_demo_keeps_full_map_and_normal16_quality_and_review():
    req = invocation('course')
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=tuple(f for f in req.context_packet.known_facts if f.label != 'existing_proof')))
    model = SelectionModel()
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
        strategy_selection=True).execute(req))
    schema = model.calls[0]['response_schema']
    assert 'PositioningNonRTBEvidenceSelection' not in schema['$defs']
    assert schema['properties']['wire_contract_version']['enum'] == ['positioning.support_selection.v11']
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert len(result.payload['outputs']) == 16
    assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
    decision, _ = run_review(list(result.payload['outputs']), verification_inputs(req))
    assert decision['status'] == 'verified', decision


def test_rtb_only_does_not_add_non_rtb_map():
    req = replace(invocation('course'), expected_outputs=('RTB',))
    model = SelectionModel()
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
        strategy_selection=True).execute(req))
    assert len(result.payload['outputs']) == 1
    assert 'PositioningNonRTBEvidenceSelection' not in model.calls[0]['response_schema']['$defs']


def test_no_eligible_primary_refuses_without_selecting_a_fallback():
    req = invocation('course')
    local = tuple(e for e in first_party_evidence(req, scoped_facts(req)) if e.input_key != 'product_truth')
    canonical = support_response_schema(PositioningWithoutSeedsOutput,
        [e.record.evidence_id for e in local], ())
    before = deepcopy(canonical)
    with pytest.raises(ModuleExecutionContractError):
        support_selection_wire_schema(canonical, PositioningWithoutSeedsOutput,
            ('value_proposition',), local, (), strategy_selection=True)
    assert canonical == before


def test_future_choice_requiring_forbidden_demo_refuses_before_model(monkeypatch):
    from app.module_execution.executors import positioning_strategy

    original = positioning_strategy.strategy_selection_catalog

    def forbidden_choice(evidence):
        catalog = deepcopy(original(evidence))
        demo_id = next(e.record.evidence_id for e in evidence if e.input_key == 'existing_proof')
        next(iter(catalog['value_proposition'].values()))['required_source_ids'].append(demo_id)
        return catalog

    monkeypatch.setattr(positioning_strategy, 'strategy_selection_catalog', forbidden_choice)
    model = AsyncMock()
    with pytest.raises(ModuleExecutionContractError):
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
            strategy_selection=True).execute(invocation('course')))
    model.assert_not_awaited()


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'integer', 'null', 'string'])
def test_non_rtb_demo_flag_retains_closed_boolean_shape(mutation):
    def select(payload, data):
        alias = demo_alias(data)
        flags = payload['outputs']['category']['evidence_support']
        if mutation == 'missing':
            flags.pop(alias)
        elif mutation == 'extra':
            flags['e999'] = False
        else:
            flags[alias] = {'integer': 0, 'null': None, 'string': 'false'}[mutation]

    model = SelectionModel(select)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
            strategy_selection=True).execute(invocation('course')))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_strategy_flags_preserve_all_aliases_and_canonical_source_limit():
    req = invocation('course')
    extras = tuple(fact(f'extra_{i}', f'Supplied qualitative context {chr(65 + i)}') for i in range(30))
    req = replace(req, expected_outputs=('category',), context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, *extras)))

    def select(payload, data):
        alias = demo_alias(data)
        flags = payload['outputs']['category']['evidence_support']
        assert len(flags) == len(data['local_evidence']) == 34
        for key in flags:
            flags[key] = key != alias
        assert Draft202012Validator(model.calls[-1]['response_schema']).is_valid(payload)

    model = SelectionModel(select)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
            strategy_selection=True).execute(req))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


@pytest.mark.parametrize('invalid', [False, True])
def test_actual_http_adapter_carries_restricted_schema_and_never_retries(monkeypatch, invalid):
    from app.orchestration_runtime.model_adapter import production_model_call

    calls = []
    selection = SelectionModel()

    def respond(request):
        body = json.loads(request.content)
        schema = body['text']['format']['schema']
        text = next(row['content'] for row in body['input'] if row['role'] == 'user')
        raw = selection.build(text=text, response_schema=schema)
        value = json.loads(raw)
        if invalid:
            alias = demo_alias(json.loads(text))
            value['outputs']['value_proposition']['primary_support_key'] = alias
            assert not Draft202012Validator(schema).is_valid(value)
        calls.append(body)
        return httpx.Response(200, json={'status': 'completed', 'output_text': json.dumps(value)})

    install_transport(monkeypatch, respond)
    req = invocation('course')
    execute = PositioningExecutor(model_call=production_model_call, support_selection_wire=True,
        strategy_selection=True, provider_schema_projection=True).execute
    if invalid:
        with pytest.raises(ExecutorOutputError) as caught:
            asyncio.run(execute(req))
        assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    else:
        result = asyncio.run(execute(req))
        quality = evaluate_result(req.execution_id, result, req.upstream_results)
        assert len(result.payload['outputs']) == 16
        assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
        decision, _ = run_review(list(result.payload['outputs']), verification_inputs(req))
        assert decision['status'] == 'verified'
    assert len(calls) == 1


def test_old_raw_v10_cannot_be_upgraded_silently():
    def old_version(payload, data):
        payload['wire_contract_version'] = 'positioning.support_selection.v10'

    model = SelectionModel(old_version)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
            strategy_selection=True).execute(invocation('course')))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_canonical_demo_rejects_even_with_approve_and_old_report_cannot_authorize_changed_sources():
    evidence = verification_inputs(invocation('course'))
    choice = dynamic_choice(evidence)
    demo_id = next(identity for identity, source in evidence.items() if source['role'] == 'demonstration')
    original = output(choice['text'], [*choice['required_source_ids'], demo_id])
    rejected, captured = run_review([original], evidence)
    assert captured['report']['assessment'] == 'APPROVE'
    assert rejected['status'] == 'rejected'
    assert rejected['findings'] == [{'output_name': 'value_proposition', 'claim_index': 0,
                                    'status': 'UNVERIFIABLE', 'reason': 'irrelevant_demonstration_citation'}]
    # Explicit synthetic counterfactual only: never repair or rerate a persisted
    # draft. A newly selected source set requires a newly bound review.
    counterfactual = output(choice['text'], choice['required_source_ids'])
    verified, current = run_review([counterfactual], evidence)
    assert verified['status'] == 'verified'
    assert captured['data']['draft_fingerprint'] != current['data']['draft_fingerprint']

    async def stale_approval(**kwargs):
        assert not Draft202012Validator(kwargs['response_schema']).is_valid(captured['report'])
        return json.dumps(captured['report'])

    result = SimpleNamespace(payload={'outputs': [counterfactual]})
    assert asyncio.run(review_positioning(stale_approval, result, evidence)) == {
        'status': 'blocked', 'reason': 'invalid_claim_review'}
