"""Execute the collector SQL probes against an explicitly disposable real DB."""
import json
import os
import subprocess
import sys

from tests.postgresql_support import mvp_database
from tests.test_production_rollout_readonly import audit


def test_real_readonly_probes_and_same_database_identity(mvp_database):
    results = []
    for source, payload in ((audit.PROBE, {'files': [], 'database': True}),
                            (audit.OPERATOR_PROBE, {'url': os.environ['MVP_TEST_DATABASE_URL']})):
        env = {**os.environ, 'DATABASE_URL': os.environ['MVP_TEST_DATABASE_URL']}
        process = subprocess.run([sys.executable, '-B', '-c', source], input=json.dumps(payload),
                                 capture_output=True, text=True, env=env, timeout=20)
        assert process.returncode == 0, process.stdout
        assert not process.stderr
        result = json.loads(process.stdout)
        assert env['DATABASE_URL'] not in process.stdout
        results.append(result.get('db', result))
    db, operator = results
    assert db['read_only'] and operator['read_only']
    assert db['heads'] == ['20261014_0012']
    assert db['identity_fingerprint'] == operator['identity_fingerprint']
    for field in ('unfinished_jobs','current_tokens','metadata_anomalies','graph_plan_anomalies','orphan_executions'):
        assert type(db[field]) is int and db[field]>=0
    assert operator['checks']['worker_admission']['epoch.UPDATE']
