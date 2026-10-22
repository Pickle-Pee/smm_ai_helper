"""Compose the original request with real executor code; never send HTTP."""
import asyncio
import runpy
from app.config import settings
settings.POSITIONING_OUTPUT_BUDGET_EXPERIMENT=128000
settings.HTTP_RETRIES=0
scope=runpy.run_module('scripts.output_budget_experiment.run_one',run_name='payload_probe')
class Verified(Exception): pass
async def stop_before_transport(**kwargs):
    raise Verified()
scope['checked_call'].__globals__['production_model_call']=stop_before_transport
try:
    asyncio.run(scope['original_execute'](scope['request']))
except Verified:
    print('PAYLOAD_VERIFIED: real executor instruction/input/schema exactly match frozen reconstruction; 0 HTTP calls')
else:
    raise AssertionError('Executor never reached frozen payload verification')
