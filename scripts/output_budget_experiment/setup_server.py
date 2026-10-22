import json
from pathlib import Path
import subprocess
import sys
import tarfile
import re

root=Path('/opt/smm_ai_helper_e2e/output-budget-experiment')
assert root.is_dir() and not root.is_symlink()
with tarfile.open(root/'source.tar') as archive:
    for m in archive.getmembers():
        assert (root/'source'/m.name).resolve().is_relative_to(root/'source') and not m.issym() and not m.islnk()
    archive.extractall(root/'source',filter='data')
source_sha=sys.argv[1]
assert re.fullmatch(r'[0-9a-f]{40}',source_sha)
(root/'SOURCE_SHA').write_text(source_sha+'\n')
subprocess.run(['docker','network','create','--internal','smm-obe-offline'],check=True)
subprocess.run(['docker','network','create','smm-obe-live'],check=True)
subprocess.run(['docker','run','-d','--name','smm-obe-db','--network','smm-obe-offline',
    '--memory','256m','--cpus','0.5','--pids-limit','128',
    '-e','POSTGRES_DB=smm_mvp_test_output_budget','-e','POSTGRES_USER=output_budget_test',
    '-e','POSTGRES_PASSWORD=isolated_test_only','--mount','type=volume,src=smm-obe-database,dst=/var/lib/postgresql/data',
    '--health-cmd','pg_isready -U output_budget_test -d smm_mvp_test_output_budget',
    '--health-interval','2s','--health-retries','30','postgres:15'],check=True)
subprocess.run(['docker','network','connect','--alias','db','smm-obe-live','smm-obe-db'],check=True)
print('New DB and networks created; no old containers modified')
