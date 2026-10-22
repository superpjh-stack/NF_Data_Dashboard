"""Local read-only HTTP application. No external services or source modifications."""
import argparse
import csv
from functools import lru_cache
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import hashlib
import json
import mimetypes
from pathlib import Path
import traceback
from urllib.parse import parse_qs,urlparse,quote

import analytics as a
import eda
from pipeline import workbook_sheets,json_value,clean

STATIC=Path(__file__).parent/'static'

@lru_cache(maxsize=40)
def cached(endpoint,query,stamp):
    p=dict(query)
    with a.connect() as db:
        if endpoint=='overview':return a.overview(db)
        if endpoint=='quality':return a.quality(db)
        return {'files':a.files,'records':a.records,'recipes':a.recipes,'stats':a.stats,'reconcile':a.reconcile}[endpoint](db,p)

def source(db,fid):
    f=db.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
    if not f:raise FileNotFoundError('등록되지 않은 원본입니다.')
    root=Path(a.meta(db)['source_root']).resolve();path=(root/f['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise FileNotFoundError('원본 경로를 찾을 수 없습니다.')
    return dict(f),path

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        if self.path!='/healthz':super().log_message(fmt,*args)
    def send(self,body,status=200,content_type='application/json; charset=utf-8',headers=None):
        if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        elif isinstance(body,str):body=body.encode()
        self.send_response(status);self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        try:self.route()
        except (ValueError,KeyError) as e:self.send({'error':str(e)},400)
        except FileNotFoundError as e:self.send({'error':str(e)},404)
        except BrokenPipeError:pass
        except Exception:
            traceback.print_exc();self.send({'error':'조회에 실패했습니다. 서버 로그를 확인하세요. 원본은 변경되지 않았습니다.'},500)
    def route(self):
        url=urlparse(self.path);path=url.path;p={k:v[0] for k,v in parse_qs(url.query).items()}
        if path=='/healthz':return self.send({'app':'needsfood-data-dashboard','status':'ok' if a.DB.exists() else 'not_ready'})
        if path in ('/','/index.html'):return self.send((STATIC/'index.html').read_bytes(),content_type='text/html; charset=utf-8')
        if path in ('/app.js','/style.css'):
            return self.send((STATIC/path[1:]).read_bytes(),content_type='application/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
        if not a.DB.exists():return self.send({'error':'데이터 분석이 준비되지 않았습니다. Refresh_Data.command를 실행하세요.'},503)
        if path.startswith('/api/'):
            endpoint=path[5:]
            if endpoint=='eda':return self.send(eda.load_report())
            if endpoint in ('overview','files','records','recipes','stats','reconcile','quality'):
                return self.send(cached(endpoint,tuple(sorted(p.items())),a.DB.stat().st_mtime_ns))
            if endpoint=='source':
                with a.connect() as db:
                    f,src=source(db,p['id']);f['sheets']=json.loads(f['sheets'])
                    f['record_count']=a.scalar(db,'SELECT count(*) FROM records WHERE file_id=?',(f['canonical_id'],))
                    f['source_changed']=hashlib.sha256(src.read_bytes()).hexdigest()!=f['sha256']
                return self.send(f)
            if endpoint=='sheet':
                with a.connect() as db:f,src=source(db,p['id'])
                if src.suffix not in ('.xlsx','.xlsb'):return self.send({'error':'이 형식은 셀 미리보기를 지원하지 않습니다. 원본을 내려받아 확인하세요.'},400)
                start=max(1,int(p.get('start','1')));limit=100;title=p.get('sheet');found=False;output=[];more=False
                generator=workbook_sheets(src)
                try:
                    for name,rs in generator:
                        if title and name!=title:continue
                        title=name;found=True
                        for ri,row in rs:
                            if ri<start:continue
                            if len(output)>=limit:more=True;break
                            output.append({'row':ri,'cells':[json_value(v) for v in row[:40]]})
                        break
                finally:generator.close()
                if not found:raise FileNotFoundError('시트가 없습니다.')
                return self.send({'sheet':title,'rows':output,'start':start,'next':output[-1]['row']+1 if more and output else None,'column_limit':40})
        if path=='/eda-report':
            d=eda.load_report();fmt=p.get('format','html')
            if fmt not in ('html','json'):raise ValueError('지원하지 않는 보고서 형식')
            body=eda.render_document(d) if fmt=='html' else d
            return self.send(body,content_type='text/html; charset=utf-8' if fmt=='html' else 'application/json; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="needsfood-eda-ml-review.{fmt}"'})
        if path=='/download':
            with a.connect() as db:f,src=source(db,p['id'])
            # Force download, including HTML, so source documents cannot execute in this origin.
            return self.send(src.read_bytes(),content_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(clean(src.name))})
        if path=='/export':
            kind=p.get('table','records');p={**p,'page':'1','size':'100'}
            with a.connect() as db:
                if kind=='files':
                    terms=[];args=[]
                    for k in ('category','status','ext'):
                        if p.get(k):terms.append(f'{k}=?');args.append(p[k])
                    if p.get('q'):terms.append('(name LIKE ? OR path LIKE ?)');args+=['%'+p['q']+'%']*2
                    where=' AND '.join(terms) or '1=1'
                    rs=a.rows(db,f'SELECT id,path,category,ext,bytes,sha256,canonical_id,status,error FROM files WHERE {where} ORDER BY path',args)
                elif kind=='recipes':rs=a.recipes(db,p,full=True)['rows']
                elif kind=='reconcile':
                    where,args=a.scope({k:v for k,v in p.items() if k in ('start','end')})
                    rec=a.rows(db,f"SELECT r.* FROM records r WHERE kind IN ('production','stock') AND {where}",args)
                    rs,_,_=a.reconcile_rows([r for r in rec if r['kind']=='production'],[r for r in rec if r['kind']=='stock'])
                    rs=[r for r in rs if (not p.get('q') or p['q'] in r['material']) and (not p.get('status') or r['status']==p['status'])]
                else:
                    where,args=a.scope(p)
                    if p.get('file_id'):where+=' AND r.file_id=?';args.append(p['file_id'])
                    rs=a.rows(db,f'SELECT r.id,r.file_id,r.kind,r.work_date,r.meal,r.menu,r.material,r.unit,r.supplier,r.portion,r.used,r.opening,r.incoming,r.closing,r.sheet,r.row,r.issues,f.path source_path FROM records r JOIN files f ON f.id=r.file_id WHERE {where} ORDER BY r.id',args)
            stream=io.StringIO();writer=csv.writer(stream)
            if rs:
                writer.writerow(rs[0].keys())
                for r in rs:
                    # CSV opened in Excel must not evaluate source strings as formulas.
                    writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in r.values()])
            return self.send(b'\xef\xbb\xbf'+stream.getvalue().encode(),content_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="needsfood-{kind}.csv"'})
        self.send({'error':'찾을 수 없는 경로입니다.'},404)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8770);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'NeedsFood dashboard: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()
