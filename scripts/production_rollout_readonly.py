"""First-rollout reconnaissance, never a deployment gate or installer.

Derived from the reviewed telemetry122_readonly.py at 39d369d: bounded subprocesses,
content-free errors, source fingerprints, repeatable-read SQL and anomaly counts.
The old five-file manifest, payload correlation, log reader and cutover gate are
deliberately excluded. Default operation is local manifest generation. Collection
requires explicit opt-in ON the authorized host; this program never uses SSH.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tarfile

TARGET = "c23dfb2cfc3cfab7cd34fe6226b67404d7d0c166"
BASE = "55b09873001931e2053210e64448fbaac64f8dcc"
# Trust anchor shipped in the reviewed collector, never supplied by legacy Git
# or a caller-controlled --expected-hash flag. Exact UTF-8/LF package bytes.
MANIFEST_SHA256 = "13623f5e33013f9bb515c1f049fc0099b44f16b4d61dd60138bab1fa333ee98d"
HOST = "nl-vmv2-nano"
PROJECT = Path("/opt/smm_ai_helper")
MAX_BYTES = 16 * 1024 * 1024


class CheckError(Exception):
    pass


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def run(args, *, cwd=None, input_text=None):
    try:
        result = subprocess.run(args, cwd=cwd, input=input_text, capture_output=True,
                                timeout=30, env={**{k:v for k,v in os.environ.items()
                                    if k.upper() != "WORKER_DRAIN_DATABASE_URL"}, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.TimeoutExpired):
        raise CheckError("command_unavailable_or_timeout") from None
    if result.returncode or len(result.stdout) > MAX_BYTES or len(result.stderr) > MAX_BYTES:
        raise CheckError("command_failed_or_output_limit")
    return result.stdout


def source_path(name):
    return name.startswith(("app/", "bot/", "migrations/", "agents_prompts/")) or name in (
        "requirements.txt", "Dockerfile", ".dockerignore", "docker-compose.yaml", "alembic.ini")


def manifest(repo):
    """Hash Git bytes, never Windows checkout/newline/mtime metadata."""
    data = run(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                "archive", "--format=tar", TARGET], cwd=repo)
    files, revisions, parents = {}, set(), set()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for entry in archive:
            if not entry.isfile() or not source_path(entry.name):
                continue
            content = archive.extractfile(entry).read()
            files[entry.name] = sha(content)
            if entry.name.startswith("migrations/versions/") and entry.name.endswith(".py"):
                for node in ast.parse(content).body:
                    key = (node.targets[0].id if isinstance(node, ast.Assign)
                           and isinstance(node.targets[0], ast.Name) else None)
                    if key in ("revision", "down_revision"):
                        value = ast.literal_eval(node.value)
                        if key == "revision":
                            revisions.add(value)
                        elif value:
                            parents.update(value if isinstance(value, tuple) else (value,))
    if revisions - parents != {"20261014_0012"}:
        raise CheckError("unexpected_migration_head")
    return dict(schema="first_rollout_manifest.v1", target=TARGET, prior_telemetry_base=BASE,
                alembic_heads=sorted(revisions - parents), files=files)


def load_target_manifest(path):
    """Authenticate package bytes without requiring any target Git object."""
    raw = Path(path).read_bytes()
    if len(raw)>MAX_BYTES or sha(raw)!=MANIFEST_SHA256:
        raise CheckError('target_manifest_digest_mismatch')
    data = json.loads(raw)
    if (data.get('schema')!='first_rollout_manifest.v1' or data.get('target')!=TARGET
            or data.get('alembic_heads')!=['20261014_0012']):
        raise CheckError('target_manifest_identity_mismatch')
    return data


def role(argv):
    # Only classifications are emitted; command arguments can contain secrets.
    words = argv if isinstance(argv, str) else " ".join(argv)
    if "app.worker" in words:
        return "worker"
    if "app.main:app" in words:
        return "backend"
    if "bot.main" in words:
        return "bot"
    return "unclassified"


# Run in each running app container using its existing Python/DB libraries. No
# application imports (and therefore no runtime/provider startup or .pyc writes).
PROBE = r'''
import hashlib, importlib.metadata, json, os, pathlib, stat, sys
def sha(b): return hashlib.sha256(b).hexdigest()
def fingerprint(v): return sha(json.dumps(v,sort_keys=True).encode())
try:
    request=json.load(sys.stdin)
    files={}; unsafe=0
    for name in request['files']:
        rel=pathlib.PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts: raise ValueError()
        p=pathlib.Path('/app')/name
        if not p.is_file() or p.is_symlink() or any(x.is_symlink() for x in p.parents):
            files[name]=None; unsafe+=1; continue
        files[name]=sha(p.read_bytes())
        for x in [p,*p.parents]:
            s=x.stat()
            if s.st_uid!=0 or s.st_gid!=0 or stat.S_IMODE(s.st_mode)&0o7022: unsafe+=1
    actual=set()
    for root in ('app','bot','migrations','agents_prompts'):
        for p in (pathlib.Path('/app')/root).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':
                actual.add(p.relative_to('/app').as_posix())
    result={'source_hashes':files,'unsafe_source_paths':unsafe,
        'extra_source_files':len(actual-set(request['files'])),
        'packages_fingerprint':fingerprint(sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions())),
        'configuration_fingerprint':fingerprint(dict(os.environ)), 'db':None}
    if request.get('database'):
        import psycopg
        url=os.environ['DATABASE_URL']
        url=url.replace('postgresql+asyncpg://','postgresql://',1)
        with psycopg.connect(url,autocommit=True,connect_timeout=5,
            options='-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000') as c:
            c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            db={'read_only':c.execute('SHOW transaction_read_only').fetchone()[0]=='on'}
            db['identity_fingerprint']=fingerprint(c.execute('SELECT current_database(), inet_server_addr()::text, inet_server_port(), (SELECT oid FROM pg_database WHERE datname=current_database())').fetchone())
            db['heads']=[r[0] for r in c.execute('SELECT version_num FROM alembic_version')]
            db['observed_at']=c.execute('SELECT statement_timestamp()::text').fetchone()[0]
            kinds="j.kind IN ('marketing.step','orchestration.module')"
            db['unfinished_jobs']=c.execute('SELECT count(*) FROM jobs j WHERE '+kinds+" AND j.status IN ('pending','running')").fetchone()[0]
            db['deferred_jobs']=c.execute('SELECT count(*) FROM jobs j JOIN job_executions e USING(job_id) WHERE '+kinds+" AND j.status IN ('pending','running') AND e.available_at>statement_timestamp()").fetchone()[0]
            db['current_tokens']=c.execute('SELECT count(*) FROM jobs j JOIN job_executions e USING(job_id) WHERE '+kinds+' AND e.claim_token IS NOT NULL').fetchone()[0]
            db['active_leases']=c.execute('SELECT count(*) FROM jobs j JOIN job_executions e USING(job_id) WHERE '+kinds+' AND e.lease_until>statement_timestamp()').fetchone()[0]
            db['expired_tokens']=c.execute('SELECT count(*) FROM jobs j JOIN job_executions e USING(job_id) WHERE '+kinds+' AND e.claim_token IS NOT NULL AND (e.lease_until IS NULL OR e.lease_until<=statement_timestamp())').fetchone()[0]
            db['metadata_anomalies']=c.execute('SELECT count(*) FROM jobs j LEFT JOIN job_executions e USING(job_id) LEFT JOIN marketing_runs r ON r.run_id=j.marketing_run_id WHERE '+kinds+" AND (r.run_id IS NULL OR (j.status IN ('pending','running') AND e.job_id IS NULL) OR (j.kind='marketing.step' AND r.workflow_type<>'marketing_mvp.v1') OR (j.kind='orchestration.module' AND r.workflow_type<>'orchestration_graph.v1'))").fetchone()[0]
            db['orphan_executions']=c.execute('SELECT count(*) FROM job_executions e LEFT JOIN jobs j USING(job_id) WHERE j.job_id IS NULL').fetchone()[0]
            db['active_runs']=c.execute("SELECT count(*) FROM marketing_runs WHERE workflow_type IN ('marketing_mvp.v1','orchestration_graph.v1') AND status IN ('queued','running')").fetchone()[0]
            db['graph_plan_anomalies']=c.execute("SELECT count(*) FROM marketing_runs r WHERE r.workflow_type='orchestration_graph.v1' AND r.status IN ('queued','running') AND (SELECT count(*) FROM orchestration_plans p WHERE p.run_id=r.run_id AND p.status='active')<>1").fetchone()[0]
            db['unknown_unfinished_kinds']=c.execute("SELECT count(*) FROM jobs j WHERE NOT ("+kinds+") AND j.status IN ('pending','running')").fetchone()[0]
            db['job_counts']=[{'lane':'fixed' if r[0]=='marketing.step' else 'graph','status':r[1] if r[1] in ('pending','running','succeeded','failed') else 'other','count':r[2]} for r in c.execute('SELECT j.kind,j.status,count(*) FROM jobs j WHERE '+kinds+' GROUP BY j.kind,j.status ORDER BY j.kind,j.status')]
            db['sessions_by_state']=[{'state':r[0] if r[0] in ('active','idle','idle in transaction','idle in transaction (aborted)','disabled') else 'other','count':r[1]} for r in c.execute('SELECT state,count(*) FROM pg_stat_activity WHERE datname=current_database() GROUP BY state')]
            # Aggregates only: no query text, client/application identity, tokens or JSON.
            present=c.execute("SELECT to_regclass('worker_admission') IS NOT NULL, to_regclass('worker_attempts') IS NOT NULL").fetchone()
            db['control_tables']=list(present)
            if all(present):
                db['admission']=[{'paused':r[0],'epoch':r[1]} for r in c.execute("SELECT paused,epoch FROM worker_admission WHERE id='workers'")]
                db['attempt_markers']=c.execute('SELECT count(*) FROM worker_attempts').fetchone()[0]
            c.execute('ROLLBACK')
            result['db']=db
    print(json.dumps(result))
except Exception:
    print(json.dumps({'error':'probe_failed'})); sys.exit(2)
'''

# Only executed by the separate protected operator command, never docker exec.
# Its credential comes from that environment, not arguments/stdin or app settings.
OPERATOR_PROBE = r'''
import hashlib,json,os,sys
try:
    import psycopg
    url=os.environ['WORKER_DRAIN_DATABASE_URL']
    if not url.startswith('postgresql+asyncpg://'): raise ValueError()
    with psycopg.connect(url.replace('postgresql+asyncpg://','postgresql://',1),autocommit=True,
        connect_timeout=5,options='-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000') as c:
        c.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        ident=c.execute('SELECT current_database(), inet_server_addr()::text, inet_server_port(), (SELECT oid FROM pg_database WHERE datname=current_database())').fetchone()
        result={'identity_fingerprint':hashlib.sha256(json.dumps(ident,sort_keys=True).encode()).hexdigest(),
            'read_only':c.execute('SHOW transaction_read_only').fetchone()[0]=='on',
            'role_flags':list(c.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()),
            'checks':{}}
        grants={'worker_admission':{'id':('SELECT','UPDATE'),'paused':('SELECT','UPDATE'),'epoch':('SELECT','UPDATE')},
            'worker_attempts':{'job_id':('SELECT',),'claim_token':('SELECT',)},
            'jobs':{'job_id':('SELECT',),'kind':('SELECT',),'status':('SELECT',)},
            'job_executions':{'job_id':('SELECT',),'claim_token':('SELECT',),'lease_until':('SELECT',),'available_at':('SELECT',)}}
        for table,columns in grants.items():
            exists=c.execute('SELECT to_regclass(%s) IS NOT NULL',(table,)).fetchone()[0]
            result['checks'][table]={'exists':exists}
            if exists:
                for column,privileges in columns.items():
                    for privilege in privileges:
                        result['checks'][table][column+'.'+privilege]=c.execute('SELECT has_column_privilege(current_user,%s,%s,%s)',(table,column,privilege)).fetchone()[0]
        result['payload_select']=c.execute("SELECT has_column_privilege(current_user,'jobs','payload_json','SELECT')").fetchone()[0]
        c.execute('ROLLBACK')
        print(json.dumps(result))
except Exception:
    print(json.dumps({'error':'operator_probe_failed'}));sys.exit(2)
'''


def operator_probe():
    """Protected host/venv subprocess; no Docker, app imports or app environment."""
    url=os.environ.get('WORKER_DRAIN_DATABASE_URL')
    if not url:
        raise CheckError('protected_operator_connection_not_supplied')
    environment={k:v for k,v in os.environ.items() if k.upper() in
                 ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP')}
    environment['WORKER_DRAIN_DATABASE_URL']=url
    try:
        response=subprocess.run([sys.executable,'-I','-B','-c',OPERATOR_PROBE],
            env=environment,capture_output=True,timeout=20)
    except (OSError,subprocess.TimeoutExpired):
        raise CheckError('operator_probe_unavailable') from None
    if response.returncode or response.stderr or len(response.stdout)>MAX_BYTES:
        raise CheckError('operator_probe_failed')
    return json.loads(response.stdout)


def operator_environment_isolated():
    # Defence against accidentally invoking this command in the application's
    # existing container/cwd. ACL/venv/package trust is additionally an operator
    # prerequisite, not something a local flag can establish.
    cwd=Path.cwd().resolve()
    return (not any(p.exists() for p in (Path('/.dockerenv'),Path('/run/.containerenv')))
            and not any(cwd==p or p in cwd.parents for p in (PROJECT,Path('/app'))))


def operator_check(recon_path):
    result=dict(schema='first_rollout_operator.v1', target=TARGET, verdict='NO_GO',
        state='operator_unverified', identity_matches=False,
        observed_at=datetime.now(timezone.utc).isoformat())
    try:
        if not operator_environment_isolated():
            raise CheckError('protected_operator_environment_required')
        raw=Path(recon_path).read_bytes()
        if len(raw)>MAX_BYTES:
            raise CheckError('recon_invalid')
        recon=json.loads(raw)
        result['recon_sha256']=sha(raw)
        if (recon.get('schema')!='first_rollout_recon.v1' or recon.get('target')!=TARGET
                or recon.get('target_manifest_sha256')!=MANIFEST_SHA256):
            raise CheckError('recon_identity_invalid')
        apps=[c for c in recon['containers'] if c['state']['Running']
              and c['role'] in ('worker','backend','bot')]
        if not apps or not any(c['role']=='worker' for c in apps):
            raise CheckError('application_db_identity_unverified')
        identities=set()
        for app in apps:
            db=recon['probes'][app['id']]['db']
            identity=db['identity_fingerprint']
            if db['read_only'] is not True or not re.fullmatch('[0-9a-f]{64}',identity):
                raise CheckError('application_db_identity_unverified')
            identities.add(identity)
        if len(identities)!=1:
            raise CheckError('application_db_identity_mismatch')
        expected=identities.pop()
        probe=operator_probe()
        result['identity_matches']=probe.get('read_only') is True and probe.get('identity_fingerprint')==expected
        if not result['identity_matches']:
            raise CheckError('operator_db_identity_mismatch')
        # Shape/boolean allowlist: never emit arbitrary subprocess/driver fields.
        flags=probe['role_flags']
        grants={'worker_admission':{'id':('SELECT','UPDATE'),'paused':('SELECT','UPDATE'),'epoch':('SELECT','UPDATE')},
            'worker_attempts':{'job_id':('SELECT',),'claim_token':('SELECT',)},
            'jobs':{'job_id':('SELECT',),'kind':('SELECT',),'status':('SELECT',)},
            'job_executions':{'job_id':('SELECT',),'claim_token':('SELECT',),'lease_until':('SELECT',),'available_at':('SELECT',)}}
        passed=(len(flags)==4 and all(flag is False for flag in flags) and probe['payload_select'] is False)
        for table,columns in grants.items():
            checks=probe['checks'][table]
            passed=passed and checks.get('exists') is True and all(
                checks.get(column+'.'+privilege) is True for column,privileges in columns.items() for privilege in privileges)
        result['role_metadata_checks_passed']=bool(passed)
        if not passed:
            raise CheckError('operator_role_metadata_unverified')
        result['state']='operator_metadata_checked'
        result['identity_fingerprint']=expected
    except Exception as exc:
        result['reason']=str(exc) if isinstance(exc,CheckError) else 'operator_check_unavailable'
    return result


def host_processes():
    result, unreadable = [], 0
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            command = (path/'cmdline').read_bytes()
            cgroup = (path/'cgroup').read_bytes()
            status = (path/'stat').read_text()
            if not command:
                continue
            argv = command.decode(errors='replace').split('\0')
            result.append(dict(pid=int(path.name), role=role(argv), command_fingerprint=sha(command),
                               cgroup_fingerprint=sha(cgroup),
                               ppid=int(status.rsplit(')', 1)[1].split()[1]),
                               network_namespace=os.readlink(path/'ns/net'),
                               start_ticks=status.rsplit(')', 1)[1].split()[19]))
        except (OSError, IndexError):
            unreadable += 1
    return dict(processes=result, unreadable=unreadable)


def listeners(raw):
    result=[]
    for line in raw.decode().splitlines():
        parts=line.split()
        if len(parts)<6:
            raise CheckError('listener_parse_failed')
        result.append(dict(protocol=parts[0], state=parts[1], local=parts[4],
                           pids=sorted(set(int(n) for n in re.findall(r'pid=(\d+)', line)))))
    return result


def container_view(c):
    config, host = c['Config'], c['HostConfig']
    labels = config.get('Labels') or {}
    return dict(id=c['Id'], image_id=c['Image'], role=role(config.get('Cmd') or []),
        service=labels.get('com.docker.compose.service'), project=labels.get('com.docker.compose.project'),
        compose_files=labels.get('com.docker.compose.project.config_files'),
        working_dir=labels.get('com.docker.compose.project.working_dir'),
        state={k:c['State'].get(k) for k in ('Running','Restarting','Paused','OOMKilled','Pid','StartedAt','FinishedAt','ExitCode')},
        restart_count=c.get('RestartCount'), restart_policy=host.get('RestartPolicy'),
        network_mode=host.get('NetworkMode'), ports=c.get('NetworkSettings',{}).get('Ports'),
        networks={k:{f:v.get(f) for f in ('NetworkID','IPAddress','GlobalIPv6Address','Aliases')}
                  for k,v in c.get('NetworkSettings',{}).get('Networks',{}).items()},
        mounts=[{k:m.get(k) for k in ('Type','Name','Source','Destination','RW')} for m in c.get('Mounts',[])],
        runtime_fingerprint=digest({'Config':config,'HostConfig':host}),
        environment_fingerprint=digest(config.get('Env',[])))


def compose_comparison(container, service, resolved, image_config):
    def env(values):
        return dict(v.split('=', 1) for v in values if '=' in v)
    expected=env(image_config.get('Env', []))
    expected.update({k:str(v) for k,v in (service.get('environment') or {}).items()})
    wanted_networks=sorted(resolved['networks'][n]['name'] for n in (service.get('networks') or ['default']))
    wanted_volumes=[]
    for m in service.get('volumes', []):
        if m.get('type')=='volume':
            source=resolved['volumes'][m['source']]['name']
        else:
            source=m.get('source')
        wanted_volumes.append((m.get('type'),source,m['target'],not m.get('read_only',False)))
    actual_volumes=[(m['Type'],m.get('Name') if m['Type']=='volume' else m.get('Source'),m['Destination'],m['RW'])
                    for m in container.get('Mounts',[])]
    return dict(environment_matches=expected==env(container['Config'].get('Env', [])),
        networks_match=wanted_networks==sorted(container.get('NetworkSettings',{}).get('Networks',{})),
        mounts_match=sorted(wanted_volumes)==sorted(actual_volumes),
        restart_matches=service.get('restart','no')==container['HostConfig'].get('RestartPolicy',{}).get('Name','no'))


def network_view(network):
    result={k:network.get(k) for k in ('Id','Name','Driver','Internal','Ingress','Scope','Containers')}
    ipam=network.get('IPAM') or {}
    result['IPAM']={'Driver':ipam.get('Driver'), 'Config':[
        {k:c.get(k) for k in ('Subnet','IPRange','Gateway')} for c in ipam.get('Config') or []]}
    result['options_fingerprint']=digest({'network':network.get('Options'),'ipam':ipam.get('Options')})
    return result


def cron_fingerprint():
    return digest({str(p):sha(p.read_bytes()) for root in
        ('/etc/crontab','/etc/cron.d','/var/spool/cron') for p in
        ([Path(root)] if Path(root).is_file() else sorted(Path(root).rglob('*'))) if p.is_file()})


def collect(manifest_path):
    if socket.gethostname()!=HOST or Path.cwd().resolve()!=PROJECT:
        raise CheckError('host_or_project_mismatch')
    data=load_target_manifest(manifest_path)
    # Force local Docker socket, ignoring DOCKER_HOST/context inherited by shell.
    docker=['docker','--host','unix:///var/run/docker.sock']
    ids=run([*docker,'ps','-aq']).decode().split()
    if not ids or any(not re.fullmatch('[0-9a-f]{12,64}', i) for i in ids):
        raise CheckError('container_inventory_unavailable')
    objects=json.loads(run([*docker,'inspect',*ids]))
    report=dict(schema='first_rollout_recon.v1', target=TARGET,
        observed_at=datetime.now(timezone.utc).isoformat(), verdict='NO_GO',
        target_manifest_sha256=MANIFEST_SHA256,
        blockers=['producer_barrier_unproven','accepted_requests_unproven',
                  'legacy_superseded_calls_unproven','external_writers_unproven','operator_unverified'],
        host=HOST, project=str(PROJECT), containers=[], probes={}, unavailable=[])
    def optional(name, operation):
        try:
            return operation()
        except Exception:
            report['unavailable'].append(name)
            return None
    report['host_processes']=host_processes()
    report['listeners']=optional('host_listeners',lambda:listeners(run(['ss','-H','-lntup'])))
    # Firewall content may contain sensitive comments. Keep only identity/change evidence.
    report['firewall_fingerprint']=optional('nft',lambda:sha(run(['nft','-j','list','ruleset'])))
    report['iptables_fingerprint']=optional('iptables',lambda:sha(run(['iptables-save'])))
    report['ip6tables_fingerprint']=optional('ip6tables',lambda:sha(run(['ip6tables-save'])))
    report['systemd_fingerprint']=optional('systemd',lambda:sha(run(['systemctl','list-units','--all','--no-legend','--no-pager'])))
    report['scheduled_tasks_fingerprint']=optional('timers',lambda:sha(run(['systemctl','list-timers','--all','--no-legend','--no-pager'])))
    report['cron_tree_fingerprint']=optional('cron',cron_fingerprint)
    report['git_head']=run(['git','rev-parse','HEAD'],cwd=PROJECT).decode().strip()
    report['git_dirty']=bool(run(['git','status','--porcelain=v1','--untracked-files=normal'],cwd=PROJECT).strip())
    report['env_file_fingerprint']=sha((PROJECT/'.env').read_bytes())
    compose_groups={}
    image_configs={}
    for c in objects:
        view=container_view(c)
        report['containers'].append(view)
        image=json.loads(run([*docker,'image','inspect',c['Image']]))[0]
        image_configs[c['Image']]=image.get('Config') or {}
        view['image_provenance']={k:image.get(k) for k in ('Id','RepoDigests','Created','Architecture','Os')}
        view['image_config_fingerprint']=digest(image.get('Config'))
        if view['state']['Running'] and view['state']['Pid']:
            pid=view['state']['Pid']
            view['network_namespace']=optional('container_namespace',lambda:os.readlink(f'/proc/{pid}/ns/net'))
            view['listeners']=optional('container_listeners',lambda:listeners(
                run(['nsenter','-t',str(pid),'-n','ss','-H','-lntup'])))
        if view['working_dir']==str(PROJECT) and view['project']:
            key=(view['project'],view['compose_files'])
            compose_groups[key]=True
        if view['state']['Running'] and view['role'] in ('worker','backend','bot'):
            probe=optional('app_probe_'+c['Id'],lambda:json.loads(run(
                [*docker,'exec','-i',c['Id'],'python','-B','-c',PROBE],
                input_text=json.dumps({'files':list(data['files']),'database':True}).encode())))
            if probe is not None:
                probe['target_sources_match']=probe['source_hashes']==data['files']
            report['probes'][c['Id']]=probe
    if not compose_groups:
        raise CheckError('compose_inventory_missing')
    # Runtime reconnaissance cannot verify a protected role. Never read/forward
    # its DSN to any application container, even if accidentally set in this shell.
    report['operator']={'state':'operator_unverified'}
    report['compose']=[]
    for (name, files) in compose_groups:
        if not files:
            raise CheckError('compose_files_missing')
        paths=[Path(p) for p in files.split(',')]
        if any(not p.is_absolute() or not p.is_file() for p in paths):
            raise CheckError('compose_files_unavailable')
        args=[*docker,'compose','--project-directory',str(PROJECT),'-p',name]
        for path in paths:
            args+=['-f',str(path)]
        resolved=json.loads(run([*args,'config','--format','json']))
        report['compose'].append(dict(project=name, files={str(p):sha(p.read_bytes()) for p in paths},
            resolved_fingerprint=digest(resolved), services={k:dict(role=role(v.get('command') or []),
            configuration_fingerprint=digest(v)) for k,v in resolved['services'].items()},
            comparisons={c['Id']:compose_comparison(c,resolved['services'][c['Config']['Labels']['com.docker.compose.service']],
                resolved,image_configs[c['Image']]) for c in objects if
                (c['Config'].get('Labels') or {}).get('com.docker.compose.project')==name and
                (c['Config'].get('Labels') or {}).get('com.docker.compose.service') in resolved['services']}))
    network_ids=run([*docker,'network','ls','-q']).decode().split()
    networks=json.loads(run([*docker,'network','inspect',*network_ids])) if network_ids else []
    report['networks']=[network_view(n) for n in networks]
    volume_ids=run([*docker,'volume','ls','-q']).decode().split()
    volumes=json.loads(run([*docker,'volume','inspect',*volume_ids])) if volume_ids else []
    report['volumes']=[{k:v.get(k) for k in ('Name','Driver','Mountpoint','Scope')} for v in volumes]
    report['inventory_complete']=False  # hashes/unknown processes are review inputs, never proof
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    local=sub.add_parser('manifest')
    local.add_argument('--repo',type=Path,default=Path.cwd())
    remote=sub.add_parser('collect')
    remote.add_argument('--manifest',type=Path,required=True)
    remote.add_argument('--execute-read-only',action='store_true')
    protected=sub.add_parser('operator',help='run only in a separate protected operator host/venv')
    protected.add_argument('--recon',type=Path,required=True)
    protected.add_argument('--execute-read-only',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.action=='manifest':
            result=manifest(args.repo)
        else:
            if not args.execute_read_only:
                raise CheckError('explicit_read_only_opt_in_required')
            result=collect(args.manifest) if args.action=='collect' else operator_check(args.recon)
    except Exception as exc:
        print(json.dumps(dict(verdict='STOP',error=str(exc) if isinstance(exc,CheckError) else 'collector_failed')))
        return 2
    if args.action=='manifest':
        raw=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
        # Preserve package bytes through Windows stdout redirection as well.
        sys.stdout.buffer.write(raw)
    else:
        print(json.dumps(result,sort_keys=True))
    return 0 if args.action=='manifest' else 2  # reconnaissance can never authorize cutover


if __name__=='__main__':
    sys.exit(main())
