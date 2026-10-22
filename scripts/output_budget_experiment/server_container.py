"""Explicit modes: test (fake credentials), migrate, or one paid cap."""
import json
from pathlib import Path
import subprocess
import sys

root=Path('/opt/smm_ai_helper_e2e/output-budget-experiment')
image='sha256:389f1c45b0fc7b46f5b59b9a371057227d4abd0ab68bf078ce409c0cacfee8c7'
mode=sys.argv[1]
assert mode in ('test','verify','migrate','128000','32000','64000')
env={'DATABASE_URL':'postgresql+asyncpg://output_budget_test:isolated_test_only@smm-obe-db:5432/smm_mvp_test_output_budget',
    'MVP_TEST_DATABASE_URL':'postgresql+asyncpg://output_budget_test:isolated_test_only@smm-obe-db:5432/smm_mvp_test_output_budget',
    'TELEGRAM_BOT_TOKEN':'123456:offline-only','OPENAI_API_KEY':'offline-not-a-key',
    'OPENAI_BASE_URL':'http://127.0.0.1:9','BOT_BACKEND_TOKEN':'offline',
    'API_BASE_URL':'http://127.0.0.1:9','PYTHONDONTWRITEBYTECODE':'1',
    'CONTROLLED_LIVE_ENABLED':'false'}
paid=mode.isdigit()
if paid or mode=='migrate':
    env['DATABASE_URL']=env['DATABASE_URL'].replace('smm_mvp_test_output_budget','output_budget_campaign')
if paid:
    private=dict(line.split('=',1) for line in Path('/opt/smm_ai_helper_e2e/secrets/staging.env').read_text().splitlines() if '=' in line)
    env.update(OPENAI_API_KEY=private['STAGING_OPENAI_API_KEY'],OPENAI_BASE_URL='https://api.openai.com/v1',
        CONTROLLED_LIVE_ENABLED='true',DEPLOYMENT_ENVIRONMENT='staging',DEFAULT_TEXT_MODEL_HARD='gpt-5-mini',
        POSITIONING_OUTPUT_BUDGET_EXPERIMENT=mode,HTTP_RETRIES='0',HTTP_TIMEOUT='600',
        GRAPH_TIMEOUT_SECONDS='780',GRAPH_LEASE_SECONDS='900',GRAPH_WORKER_CONCURRENCY='1')
    preflight=json.loads((root/'evidence/preflight.json').read_text())
    assert preflight['input_tokens']['status']==200 and preflight['campaign_upper_usd']<2
    if mode!='128000':
        a=json.loads((root/'evidence/result-128000.json').read_text())
        assert a['TRANSPORT_ACCEPTED'] and a['post_count']==1
        assert a['ledger']['status']=='ready'
    if mode=='64000':
        b=json.loads((root/'evidence/result-32000.json').read_text())
        assert b['TRANSPORT_ACCEPTED'] and b['ledger']['status']=='ready'
    # Never put an API key in argv. Docker reads a private env file on the host.
    network='smm-obe-live'
else: network='smm-obe-offline'
envpath=root/('private-live.env' if paid else 'fake-test.env')
envpath.write_text(''.join(k+'='+v+'\n' for k,v in env.items()))
envpath.chmod(0o600)
args=['docker','run','--rm','--name','smm-obe-'+mode,'--network',network,
    '--env-file',str(envpath),'--memory','768m','--cpus','1','--pids-limit','256','--read-only',
    '--tmpfs','/tmp:rw,size=128m','-v',str(root/'source')+':/workspace:ro',
    '-v',str(root)+':/campaign:rw','-w','/workspace',image]
if mode=='test':
    args += ['python','-m','pytest','-q','-p','no:cacheprovider','--tb=short',
        '--junitxml=/campaign/evidence/server-regression.xml',
        'tests/test_positioning_budget_experiment.py','tests/test_module_output_budget.py',
        'tests/test_controlled_live.py','tests/test_controlled_live_postgresql.py',
        'tests/test_graph_model_adapter.py','tests/test_production_graph_worker.py',
        'tests/test_provider_request_telemetry.py','tests/test_positioning_output.py',
        'tests/test_positioning_seed_contract.py']
elif mode=='verify': args += ['python','-m','scripts.output_budget_experiment.verify_payload']
elif mode=='migrate': args += ['alembic','upgrade','head']
else: args += ['python','-m','scripts.output_budget_experiment.run_one']
code=subprocess.call(args)
raise SystemExit(code)
