"""Read-only publication scan; report paths/counts, never secret values."""
import json
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    private = dotenv_values(ROOT / '.env')
    secrets = [str(value).encode() for name,value in private.items() if value and len(str(value))>=12
               and ('API_KEY' in name or 'SECRET' in name or 'PASSWORD' in name or name=='DATABASE_URL')]
    patterns = [rb'AIza[0-9A-Za-z_-]{35}', rb'tvly-[0-9A-Za-z_-]{20,}', rb'sk-[0-9A-Za-z_-]{30,}']
    def sensitive(data):
        return any(secret in data for secret in secrets) or any(re.search(pattern,data) for pattern in patterns)
    files = {path for path in git('ls-files','-co','--exclude-standard','-z').decode().split('\0') if path}
    findings=[]
    total=0
    for path in sorted(files):
        file=ROOT/path
        if file.is_file():
            total+=1
            if sensitive(file.read_bytes()):
                findings.append({'area':'publishable files','path':path})
    objects = git('rev-list','--objects','--all').decode().splitlines()
    scanned=0
    ids = [item.split(' ',1)[0] for item in objects]
    metadata = subprocess.check_output(['git','cat-file','--batch-check'],
        input=('\n'.join(ids)+'\n').encode(),cwd=ROOT).decode().splitlines() if ids else []
    blobs = [line.split()[0] for line in metadata if line.split()[1]=='blob']
    packed = subprocess.check_output(['git','cat-file','--batch'],
        input=('\n'.join(blobs)+'\n').encode(),cwd=ROOT) if blobs else b''
    cursor=0
    while cursor<len(packed):
        end=packed.index(b'\n',cursor)
        oid,kind,size=packed[cursor:end].split()
        length=int(size)
        content=packed[end+1:end+1+length]
        scanned+=1
        if sensitive(content):
            findings.append({'area':'Git history','object':oid.decode()})
        cursor=end+length+2
    for path in ['.env','.data/','node_modules/','.venv/','.local/','artifacts/','test-results/','.coverage']:
        if subprocess.run(['git','check-ignore','-q',path],cwd=ROOT).returncode:
            findings.append({'area':'missing ignore rule','path':path})
    print(json.dumps({'publishable_files_scanned':total,'historical_blobs_scanned':scanned,'findings':findings},indent=2))
    return bool(findings)


if __name__=='__main__':
    raise SystemExit(main())
