"""Check Git's prospective source set without staging anything or printing secrets."""
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from app.core.config import Settings
settings=Settings()
values=[s.get_secret_value().encode() for s in
        (settings.bitrefill_api_key,settings.dev_owner_credential,settings.dev_agent_credential)
        if s and len(s.get_secret_value())>=8]
files=subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=root).decode().split('\0')
problems=[]
for name in set(files):
    if not name:continue
    path=root/name
    if not path.is_file():continue
    if (path.name.startswith('.env') and path.name!='.env.example') or name.startswith('backend/docs/experiments/') or path.suffix in {'.db','.sqlite','.sqlite3','.pem','.key','.wallet'}:
        problems.append((name,'private artifact in prospective Git source set'))
        continue
    data=path.read_bytes()
    if any(value in data for value in values):
        problems.append((name,'configured credential detected'))
if problems:
    for name,reason in problems:print(f'BLOCKED: {name}: {reason}')
    raise SystemExit(1)
print('PASS: no configured credentials or private account artifacts in prospective Git source set. Nothing staged.')
