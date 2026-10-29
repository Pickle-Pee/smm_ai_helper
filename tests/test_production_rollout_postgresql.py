"""Execute the collector SQL probes against an explicitly disposable real DB."""
import json
import os
import subprocess
import sys

import pytest
from sqlalchemy.engine import make_url

from tests.test_production_rollout_readonly import audit, SCRIPT, recon_record


@pytest.fixture
def readonly_database_url():
    # Schema is prepared by CI or an existing disposable local fixture. These
    # reconnaissance tests themselves must never run a migration or issue DDL.
    raw=os.environ.get('MVP_TEST_DATABASE_URL')
    if not raw:
        pytest.skip('pre-existing disposable PostgreSQL schema required')
    url=make_url(raw)
    assert url.host in ('localhost','127.0.0.1','::1','db')
    assert 'smm_mvp_test' in (url.database or '')
    return raw


def test_real_readonly_probes_and_same_database_identity(readonly_database_url, tmp_path):
    results = []
    for source, payload in ((audit.PROBE, {'files': [], 'database': True}),
                            (audit.OPERATOR_PROBE, {})):
        env = {k:v for k,v in os.environ.items() if k.upper() not in ('WORKER_DRAIN_DATABASE_URL','DATABASE_URL')}
        env['DATABASE_URL' if source==audit.PROBE else 'WORKER_DRAIN_DATABASE_URL']=readonly_database_url
        process = subprocess.run([sys.executable, '-B', '-c', source], input=json.dumps(payload),
                                 capture_output=True, text=True, env=env, timeout=20)
        assert process.returncode == 0, process.stdout
        assert not process.stderr
        result = json.loads(process.stdout)
        assert readonly_database_url not in process.stdout
        results.append(result.get('db', result))
    db, operator = results
    assert db['read_only'] and operator['read_only']
    assert db['heads'] == ['20261026_0013']
    assert db['identity_fingerprint'] == operator['identity_fingerprint']
    for field in ('unfinished_jobs','current_tokens','metadata_anomalies','graph_plan_anomalies','orphan_executions'):
        assert type(db[field]) is int and db[field]>=0
    assert operator['checks']['worker_admission']['epoch.UPDATE']
    # Real protected CLI and isolated interpreter. The disposable DB owner is
    # intentionally overprivileged, so identity matches but it cannot be verified
    # as a restricted production operator role.
    recon=recon_record(db['identity_fingerprint'])
    path=tmp_path/'recon.json'
    path.write_text(json.dumps(recon))
    process=subprocess.run([sys.executable,'-B',str(SCRIPT),'operator','--recon',str(path),
                            '--execute-read-only'],capture_output=True,text=True,env=env,cwd=tmp_path,timeout=30)
    assert process.returncode==2
    assert not process.stderr and readonly_database_url not in process.stdout
    result=json.loads(process.stdout)
    assert result['verdict']=='NO_GO' and result['state']=='operator_unverified'
    # Containers are disallowed operator environments. GitHub's python job and
    # the local Windows host execute outside an application container.
    if audit.operator_environment_isolated():
        assert result['identity_matches']
        assert result['reason']=='operator_role_metadata_unverified'
