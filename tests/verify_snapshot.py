"""Verify the real snapshot, independent workbook evidence and local HTTP API."""
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import analytics as a
from pipeline import workbook_sheets,json_value

BASE='http://127.0.0.1:8770'
ROOT=Path(__file__).resolve().parents[1]

def get(path,params=None):
    with urlopen(BASE+path+('?' + urlencode(params) if params else ''),timeout=30) as response:return response.read()
def api(name,params=None):return json.loads(get('/api/'+name,params))
def verify():
    started=time.time();evidence=[]
    with a.connect() as db:
        m=a.meta(db);source=Path(m['source_root'])
        files=a.rows(db,'SELECT * FROM files');counts=dict(db.execute('SELECT kind,count(*) FROM records GROUP BY kind'))
        assert len(files)==m['file_count']
        assert sum(counts.values())==a.scalar(db,'SELECT count(*) FROM records')
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        for f in files:
            assert hashlib.sha256((source/f['path']).read_bytes()).hexdigest()==f['sha256'],f['path']
        assert a.scalar(db,"SELECT count(*) FROM records WHERE kind='production' AND menu IN ('생산량','생산일자','총생산량')")==0
        assert a.scalar(db,"SELECT count(*) FROM records r JOIN files f ON f.id=r.file_id WHERE f.status IN ('temporary','duplicate','template')")==0
        # First/middle/last records from 24 different representative workbooks.
        for kind in ('production','stock','recipe'):
            fs=a.rows(db,'SELECT DISTINCT file_id FROM records WHERE kind=? ORDER BY file_id',(kind,))
            picked=fs[::max(1,len(fs)//8)][:8]
            for item in picked:
                rs=a.rows(db,'SELECT * FROM records WHERE file_id=? AND kind=? ORDER BY id',(item['file_id'],kind))
                wanted=[rs[0],rs[len(rs)//2],rs[-1]]
                f=next(f for f in files if f['id']==item['file_id']);seen=0
                by_sheet={}
                for r in wanted:by_sheet.setdefault(r['sheet'],[]).append(r)
                gen=workbook_sheets(source/f['path'])
                try:
                    for sheet,stream in gen:
                        if sheet not in by_sheet:continue
                        pending={r['row']:r for r in by_sheet[sheet]}
                        for ri,values in stream:
                            if ri in pending:
                                r=pending.pop(ri);columns=json.loads(r['columns']);raw=json.loads(r['raw'])
                                for field,col in columns.items():
                                    actual=json_value(values[col] if col<len(values) else None)
                                    assert actual==raw[field],(f['path'],sheet,ri,field,actual,raw[field])
                                evidence.append({'kind':kind,'file_id':f['id'],'sheet':sheet,'row':ri,'fields':len(columns)})
                            if not pending:break
                finally:gen.close()
        for kind in ('production','stock','recipe'):assert any(x['kind']==kind for x in evidence)
    assert json.loads(get('/healthz'))['app']=='needsfood-data-dashboard'
    o=api('overview');assert o['files']==len(files)
    assert sum(x['n'] for x in o['statuses'])==len(files)
    assert sum(x['n'] for x in o['categories'])==len(files)
    f=api('files',{'category':'생산일지','size':5})
    assert f['rows'] and all(r['category']=='생산일지' for r in f['rows'])
    r=api('records',{'kind':'production','start':'2026-01-01','end':'2026-01-31','q':'김치','size':5})
    assert r['rows'] and all('2026-01-01'<=x['work_date']<='2026-01-31' for x in r['rows'])
    s=api('stats');assert sum(x['n'] for x in s['histogram'])==s['n']
    assert s['min']<=s['median']<=s['max']
    recipes=api('recipes',{'start':'2026-01-01','end':'2026-01-31'})
    assert recipes['stable_menus']<=recipes['repeat_menus']<=recipes['total']
    recon=api('reconcile');assert sum(recon['counts'].values())==recon['total'];assert recon['conflict_days']>=0
    assert isinstance(api('quality')['overlaps'],list)
    chosen=r['rows'][0];info=api('source',{'id':chosen['file_id']});assert not info['source_changed']
    raw=get('/download',{'id':chosen['file_id']});assert hashlib.sha256(raw).hexdigest()==info['sha256']
    sheet=api('sheet',{'id':chosen['file_id'],'sheet':chosen['sheet'],'start':chosen['row']})
    assert sheet['rows'][0]['row']==chosen['row']
    file_csv=list(csv.DictReader(io.StringIO(get('/export',{'table':'files','category':'생산일지'}).decode('utf-8-sig'))))
    assert len(file_csv)==f['total']
    recipe_csv=list(csv.DictReader(io.StringIO(get('/export',{'table':'recipes','start':'2026-01-01','end':'2026-01-31'}).decode('utf-8-sig'))))
    assert len(recipe_csv)==recipes['total']
    no=api('records',{'kind':'production','start':'2100-01-01'});assert no['total']==0
    for path,params,expected in [('/api/source',{'id':'../../etc/passwd'},404),('/api/stats',{'field':'used;drop table files'},400)]:
        try:get(path,params);raise AssertionError('Expected failure')
        except HTTPError as e:assert e.code==expected
    for path in ('/','/style.css','/app.js'):assert get(path)
    report={'status':'passed','dataset_id':m['dataset_id'],'parser_version':m['parser_version'],'file_hashes_checked':len(files),'records':counts,'source_evidence_checks':len(evidence),'source_evidence':evidence,'http_endpoints_checked':['healthz','overview','files','records','recipes','stats','reconcile','quality','source','sheet','download','export'],'reconciliation':{k:recon[k] for k in ('total','counts','common_days','excluded_days','conflict_days')},'browser_verification':'not_performed_origin_approval_declined','seconds':round(time.time()-started,2)}
    (ROOT/'reports/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='source_evidence'},ensure_ascii=False,indent=2))

if __name__=='__main__':verify()
