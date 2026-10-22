"""Non-generating model lookup and exact-equivalent Responses token count."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import urllib.error

root = Path('/opt/smm_ai_helper_e2e/output-budget-experiment')
assert root.is_dir() and not root.is_symlink()
out = root / 'evidence'
out.mkdir(exist_ok=True)
names = ['smm_ai_helper-' + s + '-1' for s in ('backend', 'worker', 'bot', 'db', 'redis')]
def health():
    containers = json.loads(subprocess.check_output(['docker', 'inspect', *names]))
    return [{'id': c['Id'], 'name': c['Name'], 'image': c['Image'],
        'started': c['State']['StartedAt'], 'status': c['State']['Status'],
        'health': c['State'].get('Health', {}).get('Status'), 'restarts': c['RestartCount']}
        for c in containers]
baseline = health()
(out/'baseline.json').write_text(json.dumps(baseline, indent=2))
old = Path('/opt/smm_ai_helper_e2e')
hashes = {str(p.relative_to(old)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in (old/'evidence').iterdir() if p.is_file()}
(out/'old-evidence-hashes.json').write_text(json.dumps(hashes, indent=2))
private = dict(line.split('=',1) for line in (old/'secrets/staging.env').read_text().splitlines() if '=' in line)
key = private['STAGING_OPENAI_API_KEY']
payload = json.loads((root/'frozen-request.json').read_text())
def request(path, body=None):
    req = urllib.request.Request('https://api.openai.com/v1/'+path,
        headers={'Authorization': 'Bearer '+key, 'Content-Type':'application/json'},
        data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
        method='POST' if body is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return {'status':response.status, 'body':json.load(response),
                'headers': {k:v for k,v in response.headers.items() if k.lower().startswith('x-ratelimit') or k.lower()=='x-request-id'}}
    except urllib.error.HTTPError as exc:
        data=json.loads(exc.read())
        error=data.get('error',{})
        return {'status':exc.code,'error':{k:error.get(k) for k in ('type','code','param','message')}}
model = request('models/gpt-5-mini')
count_body = {k:payload[k] for k in ('model','input','text','reasoning')}
count = request('responses/input_tokens',count_body)
result={'model_lookup':model,'input_tokens':count,
    'raw_body_preserved':False,'generation_posts':0,
    'schema_sha256':hashlib.sha256(json.dumps(payload['text']['format']['schema'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
if count['status']==200:
    tokens=count['body']['input_tokens']
    result['context_headroom_128k']=400000-tokens-128000
    result['upper_usd_by_cap']={str(cap): tokens*.25/1e6+cap*2/1e6 for cap in (128000,32000,64000)}
    result['campaign_upper_usd']=sum(result['upper_usd_by_cap'].values())
    assert result['context_headroom_128k']>=0 and result['campaign_upper_usd']<2
(out/'preflight.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
