"""One explicitly selected budget; no campaign loop or retries."""
import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path
import time

from sqlalchemy import select
from jsonschema import Draft202012Validator

from app.config import settings
from app.db import AsyncSessionLocal, engine
from app.llm import openai_text
from app.models import Job, JobExecution, MarketingRun, User
from app.module_execution import ModuleExecutionRequest
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors.positioning import PositioningExecutor
from app.module_execution.registry import ModuleExecutorRegistry
from app.orchestration_runtime.contracts import CompiledExecutionNode, CompiledExecutionPlan, PLAN_SCHEMA, module_job_id
from app.orchestration_runtime.serialization import bounded, fingerprint, plan_from_json, result_to_json
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from app.orchestration_runtime.model_adapter import production_model_call

root=Path('/campaign')
cap=settings.POSITIONING_OUTPUT_BUDGET_EXPERIMENT
assert cap in (128000,32000,64000) and settings.HTTP_RETRIES==0
frozen=json.loads((root/'frozen-request.json').read_text())
frozen['max_output_tokens']=cap
source=plan_from_json(json.loads((root/'saved-plan.json').read_text()))
node=source.nodes[0]
coverage={'schema_version':'evidence_coverage.v1','limitations':[{'code':c} for c in source.limitations],
          'accepted_node_ids':[],'competitors_supplied':0,'competitors_accepted':0}
packet=replace(node.context_packet,open_questions=(*node.context_packet.open_questions,
    'Evidence coverage (limitations, not factual claims): '+json.dumps(coverage,sort_keys=True)))
request=ModuleExecutionRequest(execution_id='c88e4588fa0d9bbb73a55a9b8d4bbc37',module_id=node.module_id,
    objective=node.objective,expected_outputs=node.expected_outputs,context_packet=packet)
# Preserve the old evidence-ID preimage ONLY as input fixture. New durable run/job,
# lease, owner, request key and ledger are created in an entirely separate DB.
run_id=f'obe20261023-{cap}'
job_id=module_job_id(run_id,1,node.node_id)
summary={'cap':cap,'run_id':run_id,'job_id':job_id,'fixture_module_execution_id':request.execution_id,
    'TRANSPORT_ACCEPTED':False,'SCHEMA_ACCEPTED':None,'SEMANTICS_ACCEPTED':None,'QUALITY_ACCEPTED':None,
    'model_requested':'gpt-5-mini','post_count':0}
output=root/'evidence'/f'result-{cap}.json'
original_post=openai_text._post_response
async def observed_post(client,url,**kwargs):
    assert kwargs['payload']==frozen, 'Frozen payload mismatch before admission/POST'
    assert summary['post_count']==0, 'Second POST prohibited'
    summary['post_count']+=1
    started=time.monotonic()
    try:
        response=await original_post(client,url,**kwargs)
        summary['http_status']=response.status_code
        summary['provider_request_id']=response.headers.get('x-request-id')
        summary['rate_limit_headers']={k:v for k,v in response.headers.items() if k.lower().startswith('x-ratelimit')}
        (root/'evidence'/f'provider-response-{cap}.json').write_bytes(response.content)
        data=response.json()
        summary.update({k:data.get(k) for k in ('id','model','status','incomplete_details','usage')})
        summary['output_item_count']=len(data.get('output',[]))
        summary['TRANSPORT_ACCEPTED']=response.status_code==200 and data.get('status')=='completed'
        if summary['TRANSPORT_ACCEPTED']:
            text=openai_text._single_attempt_output(data)
            summary['json_bytes']=len(text.encode())
            (root/'evidence'/f'output-{cap}.json').write_text(text)
            try:
                decoded=json.loads(text)
                Draft202012Validator(frozen['text']['format']['schema']).validate(decoded)
                summary['SCHEMA_ACCEPTED']=True
                summary['output_names']=[o['output_name'] for o in decoded['outputs']]
            except Exception as exc:
                summary['SCHEMA_ACCEPTED']=False
                summary['schema_error_type']=type(exc).__name__
        return response
    finally:
        summary['duration_seconds']=round(time.monotonic()-started,3)
        output.write_text(json.dumps(summary,indent=2))
openai_text._post_response=observed_post

async def checked_call(**kwargs):
    expected=frozen['input']
    assert kwargs['instruction']==expected[0]['content']
    assert kwargs['text']==expected[1]['content']
    assert kwargs['response_schema']==frozen['text']['format']['schema']
    return await production_model_call(**kwargs)

executor=PositioningExecutor(model_call=checked_call,provider_schema_projection=False,product_support_wire=False)
original_execute=executor.execute
async def frozen_execute(runtime_request):
    assert runtime_request.context_packet==request.context_packet
    try:
        result=await original_execute(request)
        summary['SEMANTICS_ACCEPTED']=True
        (root/'evidence'/f'normalized-{cap}.json').write_text(json.dumps(result_to_json(result),ensure_ascii=False,indent=2))
        quality=evaluate_result(job_id,result,())
        summary['quality']=quality
        summary['QUALITY_ACCEPTED']=fully_accepted(result,quality['accepted_result_ids'],quality['accepted_claim_ids'])
        return result
    except Exception as exc:
        summary['executor_error_type']=type(exc).__name__
        summary['executor_error_stage']=getattr(getattr(exc,'stage',None),'value',None)
        summary['semantic_rule']=getattr(getattr(exc,'rule',None),'value',None)
        if summary['SCHEMA_ACCEPTED']:
            summary['SEMANTICS_ACCEPTED']=False
        raise
    finally:
        output.write_text(json.dumps(summary,indent=2))
executor.execute=frozen_execute

async def main():
    # Exclusive local marker supplements durable admission; never replaces it.
    with (root/'evidence'/f'attempt-{cap}.json').open('x') as marker:
        json.dump({'run_id':run_id,'job_id':job_id,'cap':cap},marker)
    executors=ModuleExecutorRegistry([executor])
    single_node=CompiledExecutionNode(node.node_id,node.module_id,node.objective,node.expected_outputs,packet,(),node.binding)
    plan=CompiledExecutionPlan(PLAN_SCHEMA,source.source_plan_id,'explicit_single_module_v1',source.registry_version,(single_node,),(),'')
    raw=bounded(plan);raw.pop('execution_fingerprint')
    plan=replace(plan,execution_fingerprint=fingerprint(raw))
    service=GraphExecutionService(AsyncSessionLocal,executors=executors,controlled_live=True,lease_seconds=900,max_attempts=1)
    async with AsyncSessionLocal() as session,session.begin():
        user=User(telegram_id=12920261023)
        found=await session.scalar(select(User).where(User.telegram_id==12920261023))
        if found is None:
            session.add(user);await session.flush();owner=user.id
        else: owner=found.id
    await service.start_compiled_run(owner_id=owner,run_id=run_id,plan=plan)
    await ModuleGraphWorker(service,timeout_seconds=780).once(job_id)
    async with AsyncSessionLocal() as session:
        job=await session.get(Job,job_id)
        lease=await session.get(JobExecution,job_id)
        run=await session.get(MarketingRun,run_id)
        summary.update(job_status=job.status.value,run_status=run.status,run_error=run.error,
            attempts=lease.attempts,active_lease=lease.claim_token is not None)
        from app.llm.controlled_live import ControlledLiveAdmission
        ledger=await session.get(MarketingRun,ControlledLiveAdmission(AsyncSessionLocal).ledger_id)
        summary['ledger']={'status':ledger.status,'calls':ledger.state_json['calls'],'budgets':ledger.state_json['budgets']} if ledger else None
    usage=summary.get('usage') or {}
    if type(usage.get('input_tokens')) is int and type(usage.get('output_tokens')) is int:
        cached=(usage.get('input_tokens_details') or {}).get('cached_tokens',0)
        summary['estimated_usd']=((usage['input_tokens']-cached)*.25+cached*.025+usage['output_tokens']*2)/1e6
        summary['visible_output_tokens']=usage['output_tokens']-(usage.get('output_tokens_details') or {}).get('reasoning_tokens',0)
        summary['budget_fraction']=usage['output_tokens']/cap
    output.write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
    await engine.dispose()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
