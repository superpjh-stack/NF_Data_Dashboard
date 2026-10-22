"""Deploy a verified read-only release to the user's existing Hostinger VPS."""
from datetime import datetime,timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

import analytics as a
import eda

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.deployment'
HOST='root@187.52.127.215'
SSH=['ssh','-i',str(Path.home()/'.ssh/hostinger'),'-o','BatchMode=yes','-o','ConnectTimeout=15']
REMOTE='/docker/nf-data-dashboard'
DOMAIN='srv1934103.hstgr.cloud'
TLS='/var/lib/docker/volumes/rodem-mes_caddy_data/_data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/'+DOMAIN

def remote(script,capture=False):
    result=subprocess.run(SSH+[HOST,'python3 -'],input=script,text=True,check=True,capture_output=capture)
    return result.stdout if capture else None

def sync(sources,destination,extra=()):
    cmd=['rsync','-az','--partial','--exclude','__pycache__','--exclude','.DS_Store','-e',shlex.join(SSH),*extra,'--']
    for attempt in range(3):
        try:subprocess.run(cmd+[str(p) for p in sources]+[HOST+':'+destination],check=True);return
        except subprocess.CalledProcessError:
            if attempt==2:raise
            print('Transfer interrupted; resuming…',flush=True);time.sleep(3)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(base,login,manifest):
    authorization='Basic '+base64.b64encode((login['user']+':'+login['password']).encode()).decode()
    def get(path,auth=True):
        request=Request(base+path,headers={'Authorization':authorization} if auth else {})
        with urlopen(request,timeout=90) as r:return r.read(),dict(r.headers)
    for i in range(45):
        try:
            body,_=get('/healthz',False)
            if json.loads(body)['status']=='ok':break
        except (OSError,URLError):time.sleep(2)
    else:raise RuntimeError('HTTPS readiness timed out')
    paths=['/','/app.js','/style.css','/api/overview','/api/eda','/api/files?size=3','/api/records?kind=production&size=3','/api/recipes','/api/reconcile','/api/quality','/eda-report?format=html','/eda-report?format=json','/export?table=files&category='+urlencode({'q':'생산일지'})[2:]]
    for path in paths:
        try:get(path,False);raise AssertionError('Unauthenticated data access: '+path)
        except HTTPError as e:
            assert e.code==401,(path,e.code);e.close()
        body,_=get(path)
        if path=='/api/overview':
            overview=json.loads(body)
            assert overview['meta']['dataset_id']==manifest['dataset_id']
            assert {r['label']:r['n'] for r in overview['kinds']}==manifest['records']
            assert len(overview['summary'])==20
        if path=='/api/eda':
            report=json.loads(body);assert report['source_meta']['dataset_id']==manifest['dataset_id'];assert len(report['summary'])==20
        print('  HTTPS 401/200:',path.split('?')[0],flush=True)
    record=json.loads(get('/api/records?kind=production&size=1')[0])['rows'][0]
    params={'id':record['file_id']}
    detail=json.loads(get('/api/source?'+urlencode(params))[0]);assert not detail['source_changed']
    original,_=get('/download?'+urlencode(params));assert hashlib.sha256(original).hexdigest()==detail['sha256']
    sheet=json.loads(get('/api/sheet?'+urlencode({**params,'sheet':record['sheet'],'start':record['row']}))[0])
    assert sheet['rows'][0]['row']==record['row']
    for path in ['/api/source?'+urlencode(params),'/download?'+urlencode(params),'/api/sheet?'+urlencode(params)]:
        try:get(path,False);raise AssertionError('Unauthenticated source access')
        except HTTPError as e:assert e.code==401;e.close()
    print('  Original hash, mounted sheet preview, and row counts verified.',flush=True)
    return {'status':'passed','url':base,'dataset_id':manifest['dataset_id'],'records':manifest['records'],'source_files_verified':len(manifest['sources']),'https_routes_verified':len(paths)+3,'unauthenticated_data_status':401}

def main():
    os.chdir(ROOT);os.umask(0o077);LOCAL.mkdir(exist_ok=True)
    print('[1/7] Checking local snapshot and source manifest',flush=True)
    with a.connect() as db:
        meta=a.meta(db);source=Path(meta['source_root']);sources=a.rows(db,'SELECT path,sha256,bytes FROM files ORDER BY path')
        counts=dict(db.execute('SELECT kind,count(*) FROM records GROUP BY kind'))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    eda.load_report()
    manifest={'dataset_id':meta['dataset_id'],'records':counts,'sources':sources,'database_sha256':sha(a.DB),'eda_sha256':sha(eda.REPORT)}
    for item in sources:
        if sha(source/item['path'])!=item['sha256']:raise RuntimeError('Source changed; refresh data before deploying: '+item['path'])
    local_manifest=LOCAL/'manifest.json';local_manifest.write_text(json.dumps(manifest,ensure_ascii=False))
    release=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');release_dir=REMOTE+'/releases/'+release
    print('[2/7] Preparing isolated release '+release,flush=True)
    login=json.loads(remote(f'''
import json,os,secrets
from pathlib import Path
os.umask(0o077)
root=Path({REMOTE!r});root.mkdir(mode=0o700,parents=True,exist_ok=True)
release=Path({release_dir!r});release.mkdir(parents=True)
for part in ('data','reports','originals'): (release/part).mkdir()
old=root/'.env';env={{}}
if old.exists():env=dict(line.split('=',1) for line in old.read_text().splitlines() if '=' in line)
env.update(DASHBOARD_USER=env.get('DASHBOARD_USER') or 'needsfood',DASHBOARD_PASSWORD=env.get('DASHBOARD_PASSWORD') or secrets.token_urlsafe(24),DASHBOARD_PORT=env.get('DASHBOARD_PORT','8770'),TLS_DIRECTORY=env.get('TLS_DIRECTORY',{TLS!r}),RELEASE_DIR={release_dir!r},APP_VERSION={release!r})
certs=Path(env['TLS_DIRECTORY'])
assert (certs/'srv1934103.hstgr.cloud.crt').is_file() and (certs/'srv1934103.hstgr.cloud.key').is_file()
(root/'.candidate.env').write_text(''.join(k+'='+v+'\\n' for k,v in env.items()))
print(json.dumps({{'user':env['DASHBOARD_USER'],'password':env['DASHBOARD_PASSWORD'],'port':env['DASHBOARD_PORT'],'had_previous':old.exists()}}))
''',capture=True))
    base='https://'+DOMAIN+':'+login['port']
    access=LOCAL/'access.txt';access.write_text('NeedsFood Data Dashboard\nURL: '+base+'\nUsername: '+login['user']+'\nPassword: '+login['password']+'\nVPS configuration: '+REMOTE+'/.env\n')
    access.chmod(0o600)
    print('[3/7] Transferring application, analysis snapshot, reports, and source documents',flush=True)
    sync([ROOT/'Dockerfile',ROOT/'.dockerignore',ROOT/'requirements.txt',ROOT/'docker-compose.yml',ROOT/'src',ROOT/'deploy',local_manifest],release_dir+'/')
    sync([a.DB],release_dir+'/data/')
    sync([str(ROOT/'reports')+'/'],release_dir+'/reports/')
    sync([str(source)+'/'],release_dir+'/originals/')
    print('[4/7] Verifying remote hashes and immutable source files',flush=True)
    remote(f'''
import hashlib,json,sqlite3
from pathlib import Path
r=Path({release_dir!r})
for entry in [r,*r.rglob('*')]:
 if not entry.is_symlink():entry.chmod(0o755 if entry.is_dir() else 0o644)
m=json.loads((r/'manifest.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(r/'data/needsfood.sqlite')==m['database_sha256']
assert sha(r/'reports/eda.json')==m['eda_sha256']
for item in m['sources']:
 p=(r/'originals'/item['path']).resolve()
 assert p.is_relative_to((r/'originals').resolve()) and sha(p)==item['sha256'],item['path']
with sqlite3.connect('file:'+str(r/'data/needsfood.sqlite')+'?mode=ro',uri=True) as db:
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert dict(db.execute('SELECT kind,count(*) FROM records GROUP BY kind'))==m['records']
print('Verified sources:',len(m['sources']),'and all structured record counts.')
''')
    print('[5/7] Building and starting the isolated Docker Compose project',flush=True)
    remote(f'''
import shutil,subprocess
from pathlib import Path
root=Path({REMOTE!r});release=Path({release_dir!r})
if (root/'.env').exists():
 shutil.copy2(root/'.env',root/'.previous.env')
 if (root/'docker-compose.yml').exists():shutil.copy2(root/'docker-compose.yml',root/'.previous-compose.yml')
shutil.copy2(release/'docker-compose.yml',root/'docker-compose.yml')
cmd=['docker','compose','--project-directory',str(root),'--env-file',str(root/'.candidate.env'),'-f',str(root/'docker-compose.yml')]
subprocess.run(cmd+['config','--quiet'],check=True)
subprocess.run(cmd+['build','--pull','app'],check=True)
subprocess.run(cmd+['up','-d','--wait','--wait-timeout','180'],check=True)
''')
    print('[6/7] Verifying public HTTPS, authentication, data, reports, and original downloads',flush=True)
    try:verification=verify(base,login,manifest)
    except Exception:
        if login['had_previous']:
            print('Verification failed; restoring the previous release.',flush=True)
            remote(f'''
import shutil,subprocess
from pathlib import Path
r=Path({REMOTE!r})
shutil.copy2(r/'.previous-compose.yml',r/'docker-compose.yml')
subprocess.run(['docker','compose','--project-directory',str(r),'--env-file',str(r/'.previous.env'),'-f',str(r/'docker-compose.yml'),'up','-d','--wait'],check=True)
''')
        raise
    print('[7/7] Saving the active release and certificate reload hook',flush=True)
    remote(f'''
import os,shutil,subprocess
from pathlib import Path
r=Path({REMOTE!r});release=Path({release_dir!r})
(r/'.candidate.env').replace(r/'.env')
shutil.copy2(release/'deploy/reload_tls.py',r/'reload_tls.py')
cron=Path('/etc/cron.d/nf-data-dashboard-tls')
cron.write_text('*/30 * * * * root /usr/bin/python3 /docker/nf-data-dashboard/reload_tls.py >> /docker/nf-data-dashboard/tls-renew.log 2>&1\\n')
cron.chmod(0o644)
subprocess.run(['python3',str(r/'reload_tls.py')],check=True)
subprocess.run(['docker','compose','--project-directory',str(r),'ps'],check=True)
''')
    verification['release']=release
    (LOCAL/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2))
    remote(f"from pathlib import Path\nPath({(REMOTE+'/deployment.json')!r}).write_text({json.dumps(verification,ensure_ascii=False,indent=2)!r})\n")
    print('Deployment complete:',base,flush=True)
    print('Private login details:',access,flush=True)

if __name__=='__main__':main()
