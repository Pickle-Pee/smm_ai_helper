"""Closed staging policy, captured transport and durable no-replay coverage."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.config import Settings, settings
from app.llm import controlled_live as live
from app.model_generation_policy import ModuleOutputBudget
from app.module_registry import ModuleId
from app.orchestration_runtime.model_adapter import production_model_call
from tests.postgresql_support import mvp_database
from tests.test_controlled_live import ReceiptRows
from tests.test_graph_model_adapter import install_transport
from tests.positioning_provider import PositioningProvider
from tests.test_module_executors import dispatch, request


def configure(monkeypatch, cap=128000):
    monkeypatch.setattr(settings, 'POSITIONING_OUTPUT_BUDGET_EXPERIMENT', cap)
    monkeypatch.setattr(settings, 'CONTROLLED_LIVE_ENABLED', True)
    monkeypatch.setattr(settings, 'DEFAULT_TEXT_MODEL_HARD', 'gpt-5-mini')
    monkeypatch.setattr(live, 'correlation_fields', lambda: dict(correlation_state='graph',
        job_id='output-budget-job', run_id='output-budget-campaign', module_id='POSITIONING'))


def frozen_payload(cap=128000):
    schema = json.loads(Path(__file__).with_name('fixtures').joinpath('pr129-positioning-schema.json').read_text())
    return dict(model='gpt-5-mini', max_output_tokens=cap, reasoning={'effort':'low'}, input=[],
                text={'format':dict(type='json_schema', strict=True, schema=schema)})


@pytest.mark.parametrize('cap', [16000,32000,64000,128000])
def test_settings_closed_staging_and_timeout_chain(cap):
    values = dict(DATABASE_URL='postgresql+asyncpg://offline', TELEGRAM_BOT_TOKEN='offline',
        OPENAI_API_KEY='offline', POSITIONING_OUTPUT_BUDGET_EXPERIMENT=cap,
        CONTROLLED_LIVE_ENABLED=True, DEPLOYMENT_ENVIRONMENT='staging',
        DEFAULT_TEXT_MODEL_HARD='gpt-5-mini', HTTP_RETRIES=0, HTTP_TIMEOUT=600,
        GRAPH_TIMEOUT_SECONDS=780, GRAPH_LEASE_SECONDS=900)
    assert Settings(_env_file=None, **values).POSITIONING_OUTPUT_BUDGET_EXPERIMENT == cap
    for invalid in ({'CONTROLLED_LIVE_ENABLED':False}, {'DEPLOYMENT_ENVIRONMENT':'production'},
                    {'HTTP_RETRIES':1}, {'DEFAULT_TEXT_MODEL_HARD':'gpt-5'},
                    {'POSITIONING_OUTPUT_BUDGET_EXPERIMENT':4000},
                    {'POSITIONING_SCHEMA_PROJECTION_ENABLED':True},
                    {'POSITIONING_PRODUCT_SUPPORT_WIRE_ENABLED':True}, {'HTTP_TIMEOUT':800}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **(values | invalid))


@pytest.mark.parametrize('cap', [16000,32000,64000,128000])
def test_real_executor_transport_changes_only_cap(monkeypatch, cap):
    provider=PositioningProvider()
    install_transport(monkeypatch, provider)
    dispatch(request(ModuleId.POSITIONING), production_model_call)
    baseline=provider.calls.pop()
    configure(monkeypatch, cap)
    class Gate:
        async def reserve(self, payload): return ('key','token')
        async def finish(self, receipt, *, success): assert success
    monkeypatch.setattr(live, 'admission', Gate)
    dispatch(request(ModuleId.POSITIONING), production_model_call)
    actual=provider.calls.pop()
    assert actual.pop('max_output_tokens') == cap
    baseline.pop('max_output_tokens')
    assert actual == baseline | {'model':'gpt-5-mini'}
    dispatch(request(ModuleId.POSITIONING, outputs=('target',)), production_model_call)
    assert provider.calls[-1]['max_output_tokens']==4000


@pytest.mark.parametrize('mutation', ['cap','schema','effort','module','model'])
def test_experiment_admission_rejects_changed_contract(monkeypatch, mutation):
    configure(monkeypatch)
    payload=frozen_payload()
    if mutation=='cap': payload['max_output_tokens']=32000
    if mutation=='schema': payload['text']['format']['schema']={}
    if mutation=='effort': payload['reasoning']['effort']='medium'
    if mutation=='model': payload['model']='gpt-5'
    if mutation=='module':
        monkeypatch.setattr(live,'correlation_fields',lambda:dict(correlation_state='graph',
            job_id='job',run_id='run',module_id='CREATOR'))
    with pytest.raises(live.ControlledLiveBlocked):
        asyncio.run(live.ControlledLiveAdmission(ReceiptRows().sessions).reserve(payload))


def test_profile_order_repeat_and_three_call_limit(monkeypatch):
    configure(monkeypatch)
    rows=ReceiptRows()
    async def exercise():
        for ordinal, cap in enumerate([128000,32000,64000]):
            monkeypatch.setattr(settings,'POSITIONING_OUTPUT_BUDGET_EXPERIMENT',cap)
            monkeypatch.setattr(live,'correlation_fields',lambda:dict(correlation_state='graph',
                job_id=f'job-{ordinal}',run_id='campaign',module_id='POSITIONING'))
            gate=live.ControlledLiveAdmission(rows.sessions)
            receipt=await gate.reserve(frozen_payload(cap))
            assert rows.ledger.status=='in_flight'
            with pytest.raises(live.ControlledLiveBlocked):
                await live.ControlledLiveAdmission(rows.sessions).reserve(frozen_payload(cap))
            await gate.finish(receipt,success=True)
            with pytest.raises(live.ControlledLiveBlocked):
                await gate.reserve(frozen_payload(cap))
        assert rows.ledger.state_json['calls']==3
        assert rows.ledger.state_json['budgets']==[128000,32000,64000]
    asyncio.run(exercise())


def test_real_postgresql_experiment_receipt_survives_replacement(monkeypatch,mvp_database):
    from app.models import MarketingRun
    configure(monkeypatch)
    async def exercise():
        gate=live.ControlledLiveAdmission(mvp_database)
        try:
            receipt=await gate.reserve(frozen_payload())
            async with mvp_database() as session:
                ledger=await session.get(MarketingRun,gate.ledger_id)
                assert ledger.status=='in_flight' and ledger.state_json['calls']==1
                assert await session.get(MarketingRun,live.LEDGER_ID) is None
            with pytest.raises(live.ControlledLiveBlocked):
                await live.ControlledLiveAdmission(mvp_database).reserve(frozen_payload())
            with pytest.raises(live.ControlledLiveBlocked):
                await gate.finish((receipt[0],'stale-token'),success=True)
            await gate.finish(receipt,success=False)
            with pytest.raises(live.ControlledLiveBlocked):
                await live.ControlledLiveAdmission(mvp_database).reserve(frozen_payload())
        finally:
            async with mvp_database() as session,session.begin():
                await session.execute(delete(MarketingRun).where(MarketingRun.run_id==gate.ledger_id))
    asyncio.run(exercise())
