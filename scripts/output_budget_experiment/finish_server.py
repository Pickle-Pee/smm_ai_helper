import hashlib
import json
from pathlib import Path
import subprocess

root=Path('/opt/smm_ai_helper_e2e/output-budget-experiment')
evidence=root/'evidence'
names=['smm_ai_helper-'+s+'-1' for s in ('backend','worker','bot','db','redis')]
containers=json.loads(subprocess.check_output(['docker','inspect',*names]))
final=[{'id':c['Id'],'name':c['Name'],'image':c['Image'],'started':c['State']['StartedAt'],
    'status':c['State']['Status'],'health':c['State'].get('Health',{}).get('Status'),
    'restarts':c['RestartCount']} for c in containers]
prior=json.loads((evidence/'baseline.json').read_text())
hashes=json.loads((evidence/'old-evidence-hashes.json').read_text())
unchanged=all(hashlib.sha256((root.parent/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
snapshot_sql="select json_build_object('run_id',run_id,'status',status,'state',state_json) from marketing_runs where run_id='positioning_output_budget_20261023_v1';"
snapshot=subprocess.run(['docker','exec','smm-obe-db','psql','-U','output_budget_test','-d','output_budget_campaign','-Atc',snapshot_sql],capture_output=True,text=True)
(evidence/'ledger-final.txt').write_text(snapshot.stdout)
subprocess.run(['docker','stop','--time','20','smm-obe-db'],check=True)
secret=root/'private-live.env'
if secret.exists(): secret.unlink()
result={'production':final,'production_unchanged':final==prior,'old_evidence_unchanged':unchanged,
    'new_db_stopped':True,'new_volumes_retained':True,'new_private_key_copy_removed':True,
    'ledger_snapshot_exit_code':snapshot.returncode}
(evidence/'final-health.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
