"""One read-only GET of the newly stored failed response; no regeneration."""
import json
from pathlib import Path
import urllib.request

root=Path('/opt/smm_ai_helper_e2e/output-budget-experiment')
summary=json.loads((root/'evidence/result-128000.json').read_text())
private=dict(line.split('=',1) for line in Path('/opt/smm_ai_helper_e2e/secrets/staging.env').read_text().splitlines() if '=' in line)
request=urllib.request.Request('https://api.openai.com/v1/responses/'+summary['id'],
    headers={'Authorization':'Bearer '+private['STAGING_OPENAI_API_KEY']},method='GET')
with urllib.request.urlopen(request,timeout=60) as response:
    data=json.load(response)
    result={'http_status':response.status,'metadata':{k:data.get(k) for k in (
        'id','model','created_at','status','incomplete_details','error','usage','max_output_tokens','service_tier')},
        'output_item_count':len(data.get('output',[])),
        'get_request_id':response.headers.get('x-request-id')}
(root/'evidence/stored-response-verification.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
