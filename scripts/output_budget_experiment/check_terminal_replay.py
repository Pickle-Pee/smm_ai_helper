"""Replacement process against terminal campaign state; transport is forbidden."""
import asyncio
import json
from pathlib import Path
from sqlalchemy import select
from app.db import AsyncSessionLocal, engine
from app.models import JobExecution, MarketingRun, MarketingArtifact
from app.module_execution.executors.positioning import PositioningExecutor
from app.module_execution.registry import ModuleExecutorRegistry
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker

async def forbidden(**kwargs):
    raise AssertionError('Terminal replay attempted a provider call')

async def main():
    root=Path('/campaign/evidence')
    old=json.loads((root/'result-128000.json').read_text())
    service=GraphExecutionService(AsyncSessionLocal,
        executors=ModuleExecutorRegistry([PositioningExecutor(model_call=forbidden)]),
        controlled_live=True,lease_seconds=900,max_attempts=1)
    worked=await ModuleGraphWorker(service,timeout_seconds=780).once(old['job_id'])
    async with AsyncSessionLocal() as session:
        lease=await session.get(JobExecution,old['job_id'])
        ledger=await session.get(MarketingRun,'positioning_output_budget_20261023_v1')
        receipts=(await session.scalars(select(MarketingArtifact).where(
            MarketingArtifact.run_id=='positioning_output_budget_20261023_v1'))).all()
        result={'replacement_worker_did_work':worked,'attempts':lease.attempts,
            'active_lease':lease.claim_token is not None,'ledger_status':ledger.status,
            'ledger_calls':ledger.state_json['calls'],'receipt_count':len(receipts),
            'receipt_states':[r.payload_json['state'] for r in receipts],
            'provider_calls':0}
        assert not worked and lease.attempts==1 and lease.claim_token is None
        assert ledger.status=='blocked' and ledger.state_json['calls']==1 and len(receipts)==1
    (root/'terminal-replay.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    await engine.dispose()
asyncio.run(main())
