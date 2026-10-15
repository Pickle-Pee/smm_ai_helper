"""Read-only/security boundary regressions; no production or provider transport."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / 'scripts/production_rollout_readonly.py'
spec = importlib.util.spec_from_file_location('rollout_readonly', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_local_manifest_uses_exact_git_bytes_and_new_head(tmp_path):
    # Test a self-contained Git fixture: shallow CI checkouts need not contain
    # the historical release object. Operator collection still requires it.
    import shutil
    tree = tmp_path/'repo'
    tree.mkdir()
    root = SCRIPT.parents[1]
    wanted = json.loads((root/'docs/operations/first-production-rollout.manifest.json').read_text())
    for name in wanted['files']:
        path=tree/name
        path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/name,path)
    subprocess.run(['git','init','-q',str(tree)],check=True)
    subprocess.run(['git','-C',str(tree),'-c','core.autocrlf=true','add','.'],check=True,capture_output=True)
    subprocess.run(['git','-C',str(tree),'-c','user.name=Offline Test','-c','user.email=offline@example.invalid',
                    'commit','-qm','fixture'],check=True)
    target=subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD']).decode().strip()
    from unittest.mock import patch
    with patch.object(audit,'TARGET',target):
        first = audit.manifest(tree)
        assert first == audit.manifest(tree)
    first['target']=wanted['target']
    assert first==wanted
    assert first['target'] == audit.TARGET
    assert first['alembic_heads'] == ['20261014_0012']
    for name in ('app/worker.py', 'app/worker_control.py', 'app/services/worker_drain_service.py',
                 'app/models.py', 'app/workflows/service.py', 'app/orchestration_runtime/service.py',
                 'app/llm/telemetry.py', 'migrations/versions/20261014_0012_worker_admission.py'):
        expected = subprocess.check_output(['git', 'show', f'{target}:{name}'], cwd=tree)
        assert first['files'][name] == audit.sha(expected)


def test_cli_requires_opt_in_before_any_host_command():
    result = subprocess.run([sys.executable, str(SCRIPT), 'collect', '--manifest', 'missing.json'],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {'verdict': 'STOP', 'error': 'explicit_read_only_opt_in_required'}
    assert not result.stderr


def test_host_mismatch_precedes_manifest_or_docker(monkeypatch):
    monkeypatch.setattr(audit.socket, 'gethostname', lambda: 'offline-test')
    monkeypatch.setattr(audit, 'run', lambda *a, **k: pytest.fail('external command'))
    with pytest.raises(audit.CheckError, match='host_or_project_mismatch'):
        audit.collect({})


def test_container_and_listener_output_hides_arguments_environment_and_labels():
    secret = 'SENTINEL_CREDENTIAL_DO_NOT_PRINT'
    container = {'Id': 'a'*64, 'Image': 'sha256:'+'b'*64,
        'Config': {'Cmd': ['python', '-m', 'app.worker', secret], 'Env': ['KEY='+secret],
                   'Labels': {'untrusted.secret': secret}},
        'HostConfig': {'Binds': [secret], 'RestartPolicy': {'Name': 'unless-stopped'}},
        'State': {'Running': True, 'Error': secret}, 'NetworkSettings': {}}
    safe = audit.container_view(container)
    assert safe['role'] == 'worker'
    assert secret not in json.dumps(safe)
    safe_listeners = audit.listeners(f'tcp LISTEN 0 100 127.0.0.1:8000 0.0.0.0:* users:(("{secret}",pid=123,fd=3))\n'.encode())
    assert safe_listeners == [{'protocol':'tcp','state':'LISTEN','local':'127.0.0.1:8000','pids':[123]}]


def test_command_failures_never_echo_raw_stderr(monkeypatch, capsys):
    def broken(*a, **k):
        return subprocess.CompletedProcess(a, 1, b'', b'SENTINEL_SQL_PASSWORD')
    monkeypatch.setattr(audit.subprocess, 'run', broken)
    assert audit.main(['manifest']) == 2
    assert 'SENTINEL' not in capsys.readouterr().out


def test_compose_drift_checks_do_not_emit_values():
    secret='SENTINEL_ENV_VALUE'
    c={'Config':{'Env':['KEY='+secret]},'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}},
       'NetworkSettings':{'Networks':{'project_default':{}}},
       'Mounts':[{'Type':'volume','Name':'project_images','Destination':'/data/images','RW':True}]}
    service={'environment':{'KEY':secret},'restart':'unless-stopped',
             'volumes':[{'type':'volume','source':'images','target':'/data/images'}]}
    resolved={'networks':{'default':{'name':'project_default'}},'volumes':{'images':{'name':'project_images'}}}
    checks=audit.compose_comparison(c,service,resolved,{})
    assert all(checks.values())
    c['Config']['Env']=['KEY=drift']
    c['Mounts']=[]
    checks=audit.compose_comparison(c,service,resolved,{})
    assert not checks['environment_matches'] and not checks['mounts_match']
    assert secret not in json.dumps(checks)


def test_network_driver_options_are_never_printed():
    network={'Name':'test','IPAM':{'Driver':'plugin','Options':{'credential':'SENTINEL'},
        'Config':[{'Subnet':'172.18.0.0/16','Gateway':'172.18.0.1','private':'SENTINEL'}]},
        'Options':{'password':'SENTINEL'},'Labels':{'key':'SENTINEL'}}
    safe=audit.network_view(network)
    assert safe['IPAM']['Config'][0]['Subnet']=='172.18.0.0/16'
    assert 'SENTINEL' not in json.dumps(safe)


def test_full_collection_is_always_nogo_and_redacts_inspect(monkeypatch, tmp_path):
    secret='SENTINEL_SECRET'
    cid='a'*64
    image='sha256:'+'b'*64
    compose=tmp_path/'docker-compose.yaml'
    compose.write_text('services: {}')
    (tmp_path/'.env').write_text('KEY='+secret)
    c={'Id':cid,'Image':image,'Config':{'Cmd':['python','-m','app.worker'],
        'Env':['KEY='+secret], 'Labels':{'com.docker.compose.project':'project',
        'com.docker.compose.service':'worker','com.docker.compose.project.working_dir':str(tmp_path),
        'com.docker.compose.project.config_files':str(compose),'private':secret}},
        'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}},'State':{'Running':True,'Pid':123},
        'NetworkSettings':{'Networks':{'project_default':{}}},'Mounts':[]}
    resolved={'services':{'worker':{'command':['python','-m','app.worker'],
        'environment':{'KEY':secret},'restart':'unless-stopped'}},
        'networks':{'default':{'name':'project_default'}}}
    def runner(args,**kwargs):
        if args[0]=='git': return b'clean-sha' if args[1]=='rev-parse' else b''
        if args[0]=='docker':
            cmd=args[3:]
            if cmd==['ps','-aq']: return cid.encode()
            if cmd[0]=='inspect': return json.dumps([c]).encode()
            if cmd[:2]==['image','inspect']: return json.dumps([{'Id':image,'Config':{'Env':['KEY='+secret]}}]).encode()
            if cmd[0] in ('network','volume'): return b''
            if cmd[0]=='compose': return json.dumps(resolved).encode()
            if cmd[0]=='exec': return json.dumps({'source_hashes':{}}).encode()
            pytest.fail('unexpected Docker operation')
        if args[0]=='nft': raise audit.CheckError('unavailable')
        if args[0] in ('ss','nsenter'): return b'tcp LISTEN 0 100 0.0.0.0:8000 0.0.0.0:*\n'
        return b''
    monkeypatch.setattr(audit,'PROJECT',tmp_path)
    monkeypatch.setattr(audit.Path,'cwd',lambda:tmp_path)
    monkeypatch.setattr(audit.socket,'gethostname',lambda:audit.HOST)
    monkeypatch.setattr(audit.os,'readlink',lambda p:'net:[1]')
    monkeypatch.setattr(audit,'host_processes',lambda:{'processes':[],'unreadable':0})
    monkeypatch.setattr(audit,'run',runner)
    monkeypatch.setattr(audit,'manifest',lambda p:{'files':{}})
    monkeypatch.delenv('WORKER_DRAIN_DATABASE_URL',raising=False)
    report=audit.collect({'files':{}})
    assert report['verdict']=='NO_GO' and not report['inventory_complete']
    assert 'nft' in report['unavailable']
    assert report['containers'][0]['image_id']==image
    assert secret not in json.dumps(report)


@pytest.mark.parametrize('probe', [audit.PROBE, audit.OPERATOR_PROBE])
def test_probe_errors_are_bounded_in_real_subprocess(probe):
    result = subprocess.run([sys.executable, '-B', '-c', probe], input='{"files":["../../secret"]}',
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)['error'] in ('probe_failed', 'operator_probe_failed')
    assert not result.stderr


def test_probe_sql_is_read_only_and_does_not_select_payloads():
    for source in (audit.PROBE, audit.OPERATOR_PROBE):
        ast.parse(source)
        assert 'REPEATABLE READ READ ONLY' in source
        assert 'default_transaction_read_only=on' in source
        assert 'ROLLBACK' in source
        assert 'statement_timeout=5000' in source
        assert 'lock_timeout=1000' in source
        assert 'payload_json' not in source or "'payload_json','SELECT'" in source
        for forbidden in ('UPDATE ', 'INSERT ', 'DELETE ', 'ALTER ', 'DROP ', 'TRUNCATE ', 'FOR SHARE', 'FOR UPDATE'):
            assert forbidden not in source
    assert 'docker\",\"logs' not in SCRIPT.read_text()


@pytest.mark.parametrize('probe,probe_request', [(audit.PROBE, {'files':[], 'database':True}),
                                         (audit.OPERATOR_PROBE, {'url':'postgresql+asyncpg://local'})])
def test_real_probe_process_with_strict_readonly_adapter(tmp_path, probe, probe_request):
    # A real subprocess executes every query. The adapter rejects writes and
    # returns only aggregate metadata; it cannot hide provider/runtime imports.
    (tmp_path/'psycopg.py').write_text('''
class Cursor:
    def __init__(self, value): self.value=value
    def fetchone(self): return self.value
    def __iter__(self): return iter([self.value])
class Connection:
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def execute(self,sql,args=None):
        assert sql.startswith(('SELECT ','SHOW ','BEGIN TRANSACTION ','ROLLBACK'))
        assert not any(w in sql for w in ('UPDATE ', 'DELETE ', 'INSERT ', 'FOR SHARE', 'FOR UPDATE'))
        if sql.startswith('SHOW '): value=('on',)
        elif 'current_database(), inet_server_addr()' in sql: value=('fixture','127.0.0.1',55439,1)
        elif 'version_num' in sql: value=('20261014_0012',)
        elif 'statement_timestamp()::text' in sql: value=('2026-10-15T00:00:00Z',)
        elif 'SELECT state,count' in sql: value=('idle',1)
        elif 'SELECT j.kind,j.status,count' in sql: value=('marketing.step','succeeded',0)
        elif 'SELECT rolsuper' in sql: value=(False,False,False,False)
        elif 'to_regclass' in sql: value=(True,True)
        elif 'SELECT paused,epoch' in sql: value=(True,1)
        elif 'has_column_privilege' in sql: value=(True,)
        else: value=(0,)
        return Cursor(value)
def connect(url,**kwargs):
    assert 'default_transaction_read_only=on' in kwargs['options']
    return Connection()
''')
    import os
    env = {**os.environ, 'PYTHONPATH':str(tmp_path), 'DATABASE_URL':'postgresql://offline'}
    result = subprocess.run([sys.executable,'-B','-c',probe], cwd=tmp_path,env=env,
                            input=json.dumps(probe_request),capture_output=True,text=True)
    assert result.returncode == 0, result.stdout
    assert not result.stderr
    output = json.loads(result.stdout)
    db = output.get('db',output)
    assert db['read_only']
    assert len(db['identity_fingerprint']) == 64
