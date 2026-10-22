"""Read-only analysis. Every result is scoped to a SQLite snapshot and source evidence."""
from collections import Counter, defaultdict
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import statistics

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/needsfood.sqlite'

@contextmanager
def connect(path=DB):
    db=sqlite3.connect(f'{path.as_uri()}?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:yield db
    finally:db.close()

def rows(db,sql,args=()): return [dict(r) for r in db.execute(sql,args)]
def scalar(db,sql,args=()): return db.execute(sql,args).fetchone()[0]
def meta(db): return {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM meta')}

def scope(params, alias='r'):
    terms=[]; args=[]
    for key,col in [('start','work_date'),('end','work_date')]:
        v=params.get(key,'')
        if v: terms.append(f'{alias}.{col} '+('>=' if key=='start' else '<=')+' ?');args.append(v)
    for key in ['kind','menu','material']:
        if params.get(key):terms.append(f'{alias}.{key}=?');args.append(params[key])
    if params.get('q'):
        terms.append(f'({alias}.menu LIKE ? OR {alias}.material LIKE ? OR {alias}.supplier LIKE ?)')
        args += ['%'+params['q']+'%']*3
    return (' AND '.join(terms) if terms else '1=1'),args

def distribution(values):
    xs=sorted(v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v))
    if not xs:return {'n':0,'min':None,'max':None,'mean':None,'median':None,'q1':None,'q3':None,'stdev':None,'outliers':0,'histogram':[]}
    def q(p):
        i=(len(xs)-1)*p;a=int(i);return xs[a]+(xs[min(a+1,len(xs)-1)]-xs[a])*(i-a)
    q1,q3=q(.25),q(.75);iqr=q3-q1
    lo,hi=xs[0],xs[-1];bins=min(12,max(1,math.ceil(math.sqrt(len(xs))))) if lo!=hi else 1
    width=(hi-lo)/bins if hi!=lo else 1
    hist=[{'low':lo+i*width,'high':lo+(i+1)*width if hi!=lo else hi,'n':0} for i in range(bins)]
    for x in xs:hist[min(bins-1,int((x-lo)/width))]['n']+=1
    return {'n':len(xs),'min':lo,'max':hi,'mean':statistics.mean(xs),'median':q(.5),'q1':q1,'q3':q3,'stdev':statistics.stdev(xs) if len(xs)>1 else None,'outliers':sum(x<q1-1.5*iqr or x>q3+1.5*iqr for x in xs),'histogram':hist}

def overview(db):
    m=meta(db)
    result={'meta':m,'files':scalar(db,'SELECT count(*) FROM files'),
        'bytes':scalar(db,'SELECT sum(bytes) FROM files'),
        'categories':rows(db,'SELECT category label,count(*) n,sum(bytes) bytes FROM files GROUP BY category ORDER BY n DESC'),
        'formats':rows(db,'SELECT ext label,count(*) n FROM files GROUP BY ext ORDER BY n DESC'),
        'statuses':rows(db,'SELECT status label,count(*) n FROM files GROUP BY status ORDER BY n DESC'),
        'kinds':rows(db,'SELECT kind label,count(*) n,count(DISTINCT file_id) files FROM records GROUP BY kind'),
        'dates':dict(db.execute("SELECT min(work_date) first,max(work_date) last FROM records WHERE kind='production'").fetchone()),
        'menus':scalar(db,"SELECT count(DISTINCT menu) FROM records WHERE kind='production'"),
        'materials':scalar(db,"SELECT count(DISTINCT material) FROM records WHERE kind='production'"),
        'monthly':rows(db,"SELECT substr(work_date,1,7) month,kind,count(*) n,sum(CASE WHEN unit='kg' THEN used END) kg FROM records WHERE work_date IS NOT NULL AND kind IN ('production','stock') GROUP BY month,kind ORDER BY month"),
        'connections':[{'label':'원본 파일','status':'분석 스냅샷','note':'파일 해시·시트·행 위치를 SQLite에 보존'}, {'label':'센서 스트림','status':'미연결','note':'이 앱에 등록한 실제 수집원이 없습니다.'},{'label':'RAG / 벡터 검색','status':'미연결','note':'청킹·임베딩·벡터 DB 적재를 수행하지 않았습니다.'}]}


    kinds={r['label']:r for r in result['kinds']}
    states={r['label']:r['n'] for r in result['statuses']}
    count=lambda kind:kinds.get(kind,{}).get('n',0)
    result['summary']=[
        '이 대시보드는 니즈푸드의 조리계획서·생산일지·원료수불부가 얼마나 정리되어 있고, 어떤 확인과 분석에 쓸 수 있는지 보여줍니다.',
        f"조사한 원본은 {result['files']:,}개입니다. 원본 목록에는 같은 내용의 사본과 잠금 임시파일도 포함되어 있습니다.",
        f"같은 파일 내용의 사본 {states.get('duplicate',0):,}개는 대표본만 구조화하고, 임시파일 {states.get('temporary',0):,}개와 복사용 양식 {states.get('template',0):,}개는 분석 대상에서 분리했습니다.",
        f"원재료 표를 구조화한 대표 파일은 {states.get('extracted',0):,}개이며, 시트 미리보기만 준비한 파일은 {states.get('preview_only',0):,}개입니다. 미리보기는 표준화 완료와 다릅니다.",
        f"생산일지에서 원재료 기록 {count('production'):,}행을 읽었습니다. 이는 원재료 투입 기록 수이며 완제품 생산량이나 판매량이 아닙니다.",
        f"조리계획서에서는 계획 원재료 기록 {count('recipe'):,}행을 읽었습니다. 계획한 양과 실제로 사용한 양은 서로 다른 값으로 관리합니다.",
        f"원료수불부에서는 원재료 기록 {count('stock'):,}행을 읽었습니다. 전일재고·입고·사용량·재고량을 나누어 확인할 수 있습니다.",
        f"생산일지의 날짜 범위는 {result['dates']['first']}~{result['dates']['last']}입니다. 날짜가 적힌 기록이 없는 기간을 생산량이나 수요가 0인 기간으로 해석하지 않습니다.",
        f"생산일지에 나타난 메뉴명은 {result['menus']:,}종, 원재료명은 {result['materials']:,}종입니다. 공백을 정리한 원문 이름 기준이며 승인된 메뉴·품목 마스터의 종류 수와는 다릅니다.",
        '레시피·배합 화면에서는 같은 날짜·끼니·메뉴의 원재료 구성을 비교하고, 같은 메뉴·원재료의 1인량과 사용량 분포를 볼 수 있습니다.',
        '같은 메뉴의 원재료 구성이 달라도 고객군·계절·대체 재료에 따른 정상 차이일 수 있습니다. 구성 차이만으로 잘못된 배합이라고 판정하지 않습니다.',
        '생산·원료수불 화면에서는 두 장부에 모두 있는 날짜와 같은 원재료명을 기준으로 kg 사용량을 비교합니다. 이름이 다른 품목을 임의로 합치지 않습니다.',
        '수량 차이와 한쪽 장부에만 있는 기록은 확인할 후보입니다. 실제 입력 오류·재고 손실·불량인지 원본과 업무 맥락을 대조해야 합니다.',
        '숫자가 없는 칸과 숫자 0을 구분합니다. 수식은 다시 계산하지 않고 Excel의 마지막 저장값을 읽으므로 캐시가 없는 값은 미확인으로 남습니다.',
        f"변환 대기 문서는 {states.get('conversion_required',0):,}개, OCR을 수행하지 않은 PDF는 {states.get('ocr_not_run',0):,}개입니다. 이 문서들은 본문 추출을 마쳤다고 표시하지 않습니다.",
        '데이터 품질 화면에서는 수치·단위·재고 산식의 검토 항목을 보고, 파일·시트·행 위치로 원본 셀을 확인할 수 있습니다.',
        'EDA·ML 검토 화면에서는 결측·관측 기간·메뉴별 편차와 시간순 기준선 결과를 함께 봅니다. 통계 기준선의 검증과 학습형 ML 모델 훈련은 구분합니다.',
        '현재 센서 스트림과 RAG 문서 검색은 이 앱에 연결하지 않았습니다. 미연결은 센서 기록이나 검색용 문서가 0개라고 확인했다는 뜻이 아닙니다.',
        '원본 파일 수와 추출 행 수는 같은 자료의 서로 다른 표현이므로 합산하지 않습니다. 추출 완료도 사람이 검수하거나 승인한 상태와 다릅니다.',
        '이 화면은 마지막 분석 시점의 스냅샷입니다. 먼저 통합 현황을 보고, 필요한 원본과 EDA·ML 결과를 확인하세요. 원본 변경 후에는 데이터 새로고침을 실행해야 합니다.'
    ]
    return result

def pagination(params):
    page=max(1,int(params.get('page','1')));size=min(100,max(1,int(params.get('size','30'))));return page,size

def files(db,p):
    terms=[];args=[]
    for k in ('category','status','ext'):
        if p.get(k):terms.append(f'{k}=?');args.append(p[k])
    if p.get('q'):terms.append('(name LIKE ? OR path LIKE ?)');args += ['%'+p['q']+'%']*2
    where=' AND '.join(terms) or '1=1';page,size=pagination(p)
    return {'total':scalar(db,f'SELECT count(*) FROM files WHERE {where}',args),'page':page,'size':size,'rows':rows(db,f'SELECT id,name,path,category,ext,bytes,status,error,canonical_id FROM files WHERE {where} ORDER BY category,name LIMIT ? OFFSET ?',args+[size,(page-1)*size])}

def records(db,p):
    where,args=scope(p);page,size=pagination(p)
    if p.get('file_id'):where+=' AND r.file_id=?';args.append(p['file_id'])
    result=rows(db,f'SELECT r.*,f.name source_name FROM records r JOIN files f ON f.id=r.file_id WHERE {where} ORDER BY r.work_date DESC,r.file_id,r.sheet,r.row LIMIT ? OFFSET ?',args+[size,(page-1)*size])
    for r in result:
        for key in ('raw','columns','issues'):r[key]=json.loads(r[key])
    return {'total':scalar(db,f'SELECT count(*) FROM records r WHERE {where}',args),'page':page,'size':size,'rows':result}

def recipes(db,p,full=False):
    where,args=scope({k:v for k,v in p.items() if k not in ('kind','menu','material')})
    rec=rows(db,f"SELECT r.* FROM records r WHERE r.kind='production' AND {where}",args)
    executions=defaultdict(list)
    file_sets=defaultdict(set)
    for r in rec:
        if r['work_date']:file_sets[r['work_date']].add(r['file_id'])
    conflicts={day for day,ids in file_sets.items() if len(ids)>1}
    for r in rec:
        # Only actual dates participate in cross-day stability comparisons.
        if r['work_date'] and r['work_date'] not in conflicts:executions[(r['work_date'],r['meal'],r['menu'])].append(r)
    menus=defaultdict(list)
    for key,rs in executions.items():
        menus[key[-1]].append(tuple(sorted({r['material'] for r in rs})))
    result=[]
    for name,patterns in menus.items():
        counts=Counter(patterns);common,n=counts.most_common(1)[0]
        result.append({'menu':name,'executions':len(patterns),'variants':len(counts),'mode_share':n/len(patterns),'ingredients':len(common)})
    result.sort(key=lambda x:(-x['executions'],x['menu']))
    if p.get('q'):result=[r for r in result if p['q'] in r['menu']]
    page,size=pagination(p)
    return {'total':len(result),'page':page,'size':size,'rows':result if full else result[(page-1)*size:page*size], 'repeat_menus':sum(r['executions']>=5 for r in result),'stable_menus':sum(r['executions']>=5 and r['variants']==1 for r in result),'excluded_conflict_days':len(conflicts),'scope':'생산일지 실제 날짜·끼니·메뉴의 원재료 집합; 5회 이상 메뉴만 안정성 비율 산정'}

def stats(db,p):
    field=p.get('field','portion')
    if field not in ('portion','used'):raise ValueError('지원하지 않는 통계 항목')
    params={**p,'kind':'production'}
    where,args=scope({k:v for k,v in params.items() if k not in ('menu','material')})
    pairs=rows(db,f"SELECT menu,material,count(*) n FROM records r WHERE {where} GROUP BY menu,material ORDER BY n DESC LIMIT 200",args)
    menu=p.get('menu') or (pairs[0]['menu'] if pairs else '')
    candidate=next((r for r in pairs if r['menu']==menu),None)
    if not candidate and menu:
        candidate=next(iter(rows(db,f'SELECT menu,material,count(*) n FROM records r WHERE {where} AND menu=? GROUP BY menu,material ORDER BY n DESC LIMIT 1',args+[menu])),None)
        if candidate:pairs.append(candidate)
    material=p.get('material') or (candidate['material'] if candidate else '')
    wh,a=scope({**params,'menu':menu,'material':material})
    rs=rows(db,f"SELECT {field} value,unit FROM records r WHERE {wh}",a)
    values=[r['value'] for r in rs if r['unit']=='kg' and r['value'] is not None]
    return {**distribution(values),'menu':menu,'material':material,'field':field,'unit':'g' if field=='portion' else 'kg','excluded':len(rs)-len(values),'pairs':pairs}

def reconcile_rows(production,stock):
    """Exact normalized names, explicit kg, common actual dates; no fuzzy SKU merging."""
    dates_p={r['work_date'] for r in production if r['work_date']}
    dates_s={r['work_date'] for r in stock if r['work_date']}
    file_sets=defaultdict(set)
    for label,rs in [('production',production),('stock',stock)]:
        for r in rs:
            if r.get('file_id') and r['work_date']:file_sets[(label,r['work_date'])].add(r['file_id'])
    conflicts={key[1] for key,ids in file_sets.items() if len(ids)>1}
    common=(dates_p & dates_s)-conflicts
    maps=[]
    for rs in (production,stock):
        grouped=defaultdict(list)
        for r in rs:
            if r['work_date'] in common:grouped[(r['work_date'],r['material'])].append(r)
        maps.append(grouped)
    out=[]
    for key in sorted(maps[0].keys()|maps[1].keys()):
        a,b=maps[0].get(key,[]),maps[1].get(key,[])
        def total(rs):
            if not rs or any(r['used'] is None or r['unit']!='kg' for r in rs):return None
            return sum(r['used'] for r in rs)
        va,vb=total(a),total(b)
        # Zero stock use alone is inactive inventory, not a missing production event.
        if not a and vb==0:continue
        status=('생산에만 기록' if not b else '수불에만 기록' if not a else '비교 불가' if va is None or vb is None else '일치' if abs(va-vb)<=.01 else '수량 차이')
        out.append({'date':key[0],'material':key[1],'production':va,'stock':vb,'delta':va-vb if va is not None and vb is not None else None,'status':status,'production_source':a[0]['file_id'] if a else None,'stock_source':b[0]['file_id'] if b else None})
    return out,common,dates_p|dates_s

def reconcile(db,p):
    where,args=scope({k:v for k,v in p.items() if k not in ('kind','menu','material','q')})
    rec=rows(db,f"SELECT r.* FROM records r WHERE kind IN ('production','stock') AND {where}",args)
    rs,common,union=reconcile_rows([r for r in rec if r['kind']=='production'],[r for r in rec if r['kind']=='stock'])
    fs=defaultdict(set)
    for r in rec:
        if r['work_date']:fs[(r['kind'],r['work_date'])].add(r['file_id'])
    conflicts={key[1] for key,ids in fs.items() if len(ids)>1}
    counts=Counter(r['status'] for r in rs)
    if p.get('q'):rs=[r for r in rs if p['q'] in r['material']]
    if p.get('status'):rs=[r for r in rs if p['status']==r['status']]
    rs.sort(key=lambda r:(r['status']=='일치',-(abs(r['delta']) if r['delta'] is not None else 0),r['date']))
    page,size=pagination(p)
    return {'total':len(rs),'page':page,'size':size,'rows':rs[(page-1)*size:page*size],'counts':dict(counts),'common_days':len(common),'excluded_days':len(union-common-conflicts),'conflict_days':len(conflicts),'tolerance':.01,'basis':'실제 셀 날짜·정규화한 동일 원재료명·kg. 모든 끼니 합산. 수불 사용 0만 있는 품목은 제외.'}

def quality(db):
    issues=Counter();examples=[]
    for r in db.execute('SELECT r.id,r.file_id,r.sheet,r.row,r.kind,r.material,r.issues,f.name FROM records r JOIN files f ON f.id=r.file_id WHERE issues<>\'[]\''):
        for issue in json.loads(r['issues']):issues[issue]+=1
        if len(examples)<100:examples.append(dict(r))
    names=rows(db,"SELECT material,count(*) n FROM records WHERE kind='production' GROUP BY material ORDER BY n DESC LIMIT 15")
    # Multiple source sheets for the same date may be legitimate sections or conflicting versions.
    overlap=rows(db,"SELECT kind,work_date,count(DISTINCT file_id) files FROM records WHERE kind IN ('production','stock') AND work_date IS NOT NULL GROUP BY kind,work_date HAVING count(DISTINCT file_id)>1 ORDER BY work_date LIMIT 100")
    return {'issues':[{'label':k,'n':v} for k,v in issues.most_common()],'examples':examples,'materials':names,'overlaps':overlap,'pending':rows(db,"SELECT status label,count(*) n FROM files GROUP BY status ORDER BY n DESC"),'note':'검토 후보이며 오류·불량 확정이 아닙니다. 수식은 재계산하지 않고 Excel의 마지막 저장값을 읽습니다.'}
