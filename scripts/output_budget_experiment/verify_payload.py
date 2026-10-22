"""Compose the original request with real executor code; never send HTTP."""
import asyncio
import hashlib
import json
from pathlib import Path
import runpy
from app.config import settings
settings.POSITIONING_OUTPUT_BUDGET_EXPERIMENT=128000
settings.HTTP_RETRIES=0
scope=runpy.run_module('scripts.output_budget_experiment.run_one',run_name='payload_probe')
class Verified(Exception): pass
async def stop_before_transport(**kwargs):
    expected=scope['frozen']
    actual=kwargs['text']
    prior=expected['input'][1]['content']
    assert kwargs['instruction']==expected['input'][0]['content']
    assert kwargs['response_schema']==expected['text']['format']['schema']
    assert json.loads(actual)==json.loads(prior), 'Runtime input differs semantically from reconstruction'
    assert len(actual.encode())==9893
    evidence=Path('/campaign/evidence')
    info={'input_equal_bytes':actual==prior,'input_equal_json_values':True,
          'runtime_input_bytes':len(actual.encode()),'reconstructed_input_bytes':len(prior.encode()),
          'runtime_input_sha256':hashlib.sha256(actual.encode()).hexdigest(),
          'reconstructed_input_sha256':hashlib.sha256(prior.encode()).hexdigest(),
          'difference':'JSON object key order only' if actual!=prior else 'none', 'generation_posts':0}
    (evidence/'payload-runtime-verification.json').write_text(json.dumps(info,indent=2))
    if actual!=prior:
        path=Path('/campaign/frozen-request.json')
        with Path('/campaign/reconstructed-request-before-runtime.json').open('x') as saved:
            saved.write(path.read_text())
        expected['input'][1]['content']=actual
        path.write_text(json.dumps(expected,ensure_ascii=False))
    raise Verified()
scope['executor']._model_call=stop_before_transport
try:
    asyncio.run(scope['original_execute'](scope['request']))
except Verified:
    print('PAYLOAD_VERIFIED: real executor instruction/schema match; JSON input values match; key ordering recorded; 0 HTTP calls')
else:
    raise AssertionError('Executor never reached frozen payload verification')
