"""Reproducible read-only EDA and a temporal statistical baseline, without ML training."""
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
import argparse
import hashlib
from html import escape
import json
import math
from pathlib import Path
import statistics

import analytics as a

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/eda.json'
VERSION='1.0'
SOURCES=[
 {'title':'scikit-learn · 데이터 누출 방지','url':'https://scikit-learn.org/stable/common_pitfalls.html'},
 {'title':'scikit-learn · 시간 순서 검증','url':'https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html'},
 {'title':'scikit-learn · 중앙값 기준선','url':'https://scikit-learn.org/stable/modules/generated/sklearn.dummy.DummyRegressor.html'},
 {'title':'scikit-learn · 이상 탐지','url':'https://scikit-learn.org/stable/modules/outlier_detection.html'},
]
FIELDS={'production':[('portion','1인량','g'),('used','사용량','kg')],
        'recipe':[('portion','계획 1인량','g'),('used','계획 소요량','kg')],
        'stock':[('opening','전일재고','kg'),('incoming','입고','kg'),('used','사용량','kg'),('closing','재고량','kg')]}
LABELS={'production':'생산일지','recipe':'조리계획서','stock':'원료수불부'}

def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def percent(n,d):return 100*n/d if d else None

def describe(values):
    d=a.distribution(values)
    if d['n']:
        xs=sorted(values)
        def q(p):
            k=(len(xs)-1)*p;i=int(k);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(k-i)
        d.update(p05=q(.05),p95=q(.95),zero=sum(v==0 for v in xs),negative=sum(v<0 for v in xs))
    else:d.update(p05=None,p95=None,zero=0,negative=0)
    return d

def date_coverage(records):
    dates=sorted({r['work_date'] for r in records if r['work_date']})
    counts=Counter(r['work_date'][:7] for r in records if r['work_date'])
    months=[]
    if dates:
        y,m=map(int,dates[0][:7].split('-'));last=dates[-1][:7]
        while f'{y:04}-{m:02}'<=last:
            key=f'{y:04}-{m:02}';months.append({'month':key,'n':counts[key]})
            y,m=(y+1,1) if m==12 else (y,m+1)
    gaps=[]
    for left,right in zip(dates,dates[1:]):
        missing=(date.fromisoformat(right)-date.fromisoformat(left)).days-1
        if missing>=7:gaps.append({'after':left,'before':right,'unobserved_days':missing})
    return {'first':dates[0] if dates else None,'last':dates[-1] if dates else None,'days':len(dates),
            'dated_rows':sum(bool(r['work_date']) for r in records),'months':months,'missing_months':[r['month'] for r in months if not r['n']],
            'long_gaps':gaps,'note':'미관측 기간이며 휴무·미생산·원본 누락을 구분할 운영 달력이 없습니다.'}

def score(predictions):
    if not predictions:return {'n':0,'mae':None,'wape':None,'median_ape':None}
    errors=[abs(r['actual']-r['predicted']) for r in predictions]
    denom=sum(abs(r['actual']) for r in predictions)
    return {'n':len(predictions),'mae':statistics.mean(errors),'wape':100*sum(errors)/denom if denom else None,
            'median_ape':100*statistics.median(abs(r['actual']-r['predicted'])/abs(r['actual']) for r in predictions)}

def temporal_baseline(records,minimum_train=5,minimum_days=3):
    files=defaultdict(set)
    for r in records:
        if r['work_date']:files[r['work_date']].add(r['file_id'])
    conflicts={d for d,ids in files.items() if len(ids)>1}
    groups=defaultdict(list);excluded=Counter()
    for r in records:
        if not r['work_date']:excluded['날짜 미확인']+=1;continue
        if r['work_date'] in conflicts:excluded['여러 파일의 날짜 충돌']+=1;continue
        if r['unit']!='kg':excluded['헤더 단위 미확인']+=1;continue
        if not finite(r['portion']) or r['portion']<=0:excluded['1인량 결측·0·음수']+=1;continue
        groups[(r['work_date'],r['meal'],r['menu'],r['material'])].append(r)
    observations=[];ambiguous=0;collapsed=0
    for (day,meal,menu,material),rs in groups.items():
        vals={r['portion'] for r in rs}
        if len(vals)!=1:ambiguous+=1;continue
        collapsed+=len(rs)-1
        observations.append({'date':day,'meal':meal,'menu':menu,'material':material,'value':next(iter(vals)),'file_id':rs[0]['file_id'],'sheet':rs[0]['sheet'],'row':rs[0]['row']})
    dates=sorted({r['date'] for r in observations})
    base={'status':'insufficient_data','method':'메뉴·원재료별 과거 1인량 중앙값 vs 원재료별 과거 중앙값',
          'model_trained':False,'unit':'g','eligible_observations':len(observations),'excluded_rows':dict(excluded),
          'ambiguous_events_excluded':ambiguous,'duplicate_event_rows_collapsed':collapsed,
          'minimum_train_observations':minimum_train,'minimum_train_days':minimum_days,'predictions':[],
          'limitations':['과거 기재된 1인량을 재현하는 기준선이며 승인 배합·영양·품질의 정답이 아닙니다.',
            '고객군·규격·레시피 개정·일정 정보가 분리되어 있지 않아 집단 혼합의 영향이 있습니다.',
            '우유 등 1인량 단위 해석이 필요한 원본도 포함됩니다. 단위의 업무적 타당성은 미검수입니다.',
            '한 번의 시간 분할 결과이며 모델 선택용 교차검증·운영 검증은 수행하지 않았습니다.']}
    if len(dates)<5:return base
    split=max(1,min(len(dates)-1,int(len(dates)*.8)));cutoff=dates[split]
    train=[r for r in observations if r['date']<cutoff];test=[r for r in observations if r['date']>=cutoff]
    pair_train=defaultdict(list);material_train=defaultdict(list)
    for r in train:
        pair_train[(r['menu'],r['material'])].append(r);material_train[r['material']].append(r['value'])
    medians={key:statistics.median(r['value'] for r in rs) for key,rs in pair_train.items()
             if len(rs)>=minimum_train and len({r['date'] for r in rs})>=minimum_days}
    material_medians={key:statistics.median(values) for key,values in material_train.items()}
    predictions=[];unseen=0;insufficient=0
    for r in test:
        key=(r['menu'],r['material'])
        if key not in medians:
            if key in pair_train:insufficient+=1
            else:unseen+=1
            continue
        predictions.append({'date':r['date'],'menu':r['menu'],'material':r['material'],'actual':r['value'],
                            'predicted':medians[key],'material_predicted':material_medians[r['material']],
                            'file_id':r['file_id'],'sheet':r['sheet'],'row':r['row']})
    by_pair=defaultdict(list)
    for r in predictions:by_pair[(r['menu'],r['material'])].append(r)
    group_results=[]
    for (menu,material),rs in by_pair.items():
        group_results.append({'menu':menu,'material':material,'train_n':len(pair_train[(menu,material)]),
                              'prediction':medians[(menu,material)],**score(rs)})
    group_results.sort(key=lambda x:(-x['n'],x['menu'],x['material']))
    comparison=[{**r,'predicted':r['material_predicted']} for r in predictions]
    return {**base,'status':'evaluated','train_first':min(r['date'] for r in train),'train_last':max(r['date'] for r in train),
        'test_first':min(r['date'] for r in test),'test_last':max(r['date'] for r in test),'train_days':split,'test_days':len(dates)-split,
        'train_n':len(train),'test_n':len(test),'covered_n':len(predictions),'coverage_percent':percent(len(predictions),len(test)),
        'unseen_pair_test_n':unseen,'insufficient_pair_test_n':insufficient,'eligible_train_pairs':len(medians),
        'pair_metrics':score(predictions),'material_metrics_same_test':score(comparison),'groups':group_results[:30],
        'predictions':sorted(predictions,key=lambda r:(-abs(r['actual']-r['predicted']),r['date']))[:30],
        'split_note':'전체 날짜 기준 시간순 분할'}

def cohort_analysis(records):
    groups=defaultdict(list)
    for r in records:
        if finite(r['portion']) and r['portion']>0 and r['unit']=='kg':groups[(r['menu'],r['material'])].append(r)
    summaries=[];examples=[];eligible_n=0;outlier_n=0;zero_iqr=0
    for (menu,material),rs in groups.items():
        if len(rs)<20 or len({r['work_date'] for r in rs if r['work_date']})<5:continue
        d=describe([r['portion'] for r in rs]);iqr=d['q3']-d['q1'];lo=d['q1']-1.5*iqr;hi=d['q3']+1.5*iqr
        eligible_n+=len(rs);zero_iqr+=iqr==0
        flagged=[r for r in rs if r['portion']<lo or r['portion']>hi];outlier_n+=len(flagged)
        summaries.append({'menu':menu,'material':material,'n':d['n'],'days':len({r['work_date'] for r in rs if r['work_date']}),
            'median':d['median'],'q1':d['q1'],'q3':d['q3'],'min':d['min'],'max':d['max'],'stdev':d['stdev'],
            'cv':d['stdev']/d['mean'] if d['mean'] else None,'outliers':len(flagged),'zero_iqr':iqr==0})
        for r in flagged[:2]:
            if len(examples)<40:examples.append({k:r[k] for k in ('file_id','sheet','row','menu','material','work_date','portion')})
    summaries.sort(key=lambda r:(-r['n'],r['menu'],r['material']))
    return {'groups':len(summaries),'eligible_rows':eligible_n,'outlier_rows':outlier_n,'zero_iqr_groups':zero_iqr,
        'top':summaries[:25],'variable':sorted(summaries,key=lambda r:(-(r['cv'] or 0),-r['n']))[:20],'examples':examples,
        'note':'동일 메뉴·원재료의 양수 1인량, 표본 20행 이상·실제 날짜 5일 이상만 비교. IQR=0 집단도 별도 표시하며 비중앙값을 검토 대상으로 셉니다. 불량·오류 확정이 아닙니다.'}

def build_report():
    with a.connect() as db:
        db.execute('BEGIN')
        meta=a.meta(db);records=a.rows(db,'SELECT * FROM records ORDER BY id')
        overview=a.overview(db);rec_summary=a.recipes(db,{},full=True);reconciliation=a.reconcile(db,{})
    by={kind:[r for r in records if r['kind']==kind] for kind in FIELDS}
    domains=[]
    for kind,rs in by.items():
        numeric=[]
        for key,label,unit in FIELDS[kind]:
            valid=[r[key] for r in rs if finite(r[key]) and r['unit']=='kg']
            numeric.append({'field':key,'label':label,'unit':unit,'rows':len(rs),'filled':sum(finite(r[key]) for r in rs),
                'eligible':len(valid),'excluded':len(rs)-len(valid),'fill_percent':percent(sum(finite(r[key]) for r in rs),len(rs)),
                **describe(valid)})
        domains.append({'kind':kind,'label':LABELS[kind],'rows':len(rs),'files':len({r['file_id'] for r in rs}),
                        'menus':len({r['menu'] for r in rs if r['menu']}),'materials':len({r['material'] for r in rs}),
                        'coverage':date_coverage(rs),'numeric':numeric})
    prod,stock=by['production'],by['stock'];pn={r['material'] for r in prod};sn={r['material'] for r in stock}
    equation={'eligible':0,'within_tolerance':0,'difference':0,'unknown':0,'negative_closing':0}
    for r in stock:
        if r['unit']!='kg' or not all(finite(r[k]) for k in ('opening','incoming','used','closing')):equation['unknown']+=1;continue
        equation['eligible']+=1;difference=abs(r['opening']+r['incoming']-r['used']-r['closing'])
        equation['within_tolerance' if difference<=.001 else 'difference']+=1
        equation['negative_closing']+=r['closing']<0
    cohorts=cohort_analysis(prod);baseline=temporal_baseline(prod)
    baseline['split_note']='전체 적격 관측 날짜의 앞 80% / 뒤 20%. 같은 날짜는 한쪽 집합에만 두고 중앙값·표본 자격은 과거 구간에서만 계산.'
    recipe_var=sorted([r for r in rec_summary['rows'] if r['executions']>=5],key=lambda r:(r['mode_share'],-r['executions']))[:20]
    metrics={'names_overlap':len(pn&sn),'production_names':len(pn),'stock_names':len(sn),'production_only':len(pn-sn),'stock_only':len(sn-pn)}
    report={'report_version':VERSION,'created_at':datetime.now(timezone.utc).isoformat(),'source_meta':meta,'basis':'analysis_snapshot',
        'record_total':len(records),'files':overview['files'],'statuses':overview['statuses'],'domains':domains,
        'menu_patterns':{k:v for k,v in rec_summary.items() if k!='rows'},'variable_menus':recipe_var,
        'cohorts':cohorts,'name_linkage':metrics,'inventory_equation':equation,
        'reconciliation':{k:v for k,v in reconciliation.items() if k not in ('rows','page','size')},'baseline':baseline,
        'sources':SOURCES,
        'limitations':['자료는 원본의 마지막 저장값이며 사람의 업무 검수를 거친 정답 데이터가 아닙니다.',
            '원재료 이름과 메뉴는 NFC·공백만 정리한 원문 분류입니다. 고유 이름 수를 승인 SKU 수로 해석하지 않습니다.',
            '계획서의 실제 날짜 셀은 일부만 추출되었습니다. 파일명/주차를 근거로 생산일자에 자동 연결하지 않았습니다.',
            '센서·배치 LOT·불량·폐기·잔반·고객별 확정 식수·승인 레시피·발주 리드타임은 현재 정형 스키마에 없습니다.',
            '과거 행의 사용량·전일재고·입고·재고량을 같은 시점 예측 입력으로 함께 쓰면 수식 관계와 시점 누출을 만들 수 있습니다.',
            '관측되지 않은 날짜의 수요를 0으로 채우지 않습니다. 운영 달력과 입력 누락 판별이 필요합니다.']}
    report['use_cases']=feasibility(report)
    report['findings']=findings(report)
    report['summary']=summary_lines(report)
    report['roadmap']=[
        {'stage':'1단계','title':'명칭·단위·날짜 검수','action':'상위 반복 메뉴와 원재료의 승인명·고객군·1인량 단위를 확정하고 미관측 월의 실제 누락 여부를 확인합니다.','acceptance':'대표 원본 셀 검수표, 이름 매핑 승인 이력, 운영 달력 확보'},
        {'stage':'2단계','title':'레시피 후보·입력 편차 검토','action':'현재 중앙값 기준선과 메뉴별 IQR 후보를 조리 담당자가 검토합니다. 검토 결과와 레시피 개정을 기록합니다.','acceptance':'검토 후보의 유효성 비율, 메뉴별 MAE, 새로운 메뉴의 커버리지 측정'},
        {'stage':'3단계','title':'식수 기반 소요량·발주 의사결정','action':'확정 식수·고객군·레시피 버전·재고·리드타임을 연결합니다. 산식 기준선보다 나아지는지 시간순 검증으로 비교합니다.','acceptance':'기간별/메뉴별 WAPE·MAE, 부족·과잉 비용을 별도로 평가'},
        {'stage':'이후','title':'공정·품질 ML 검토','action':'LOT·배치별 설비 시계열과 검사·불량·폐기 결과 라벨을 적재하고 연결률과 라벨 품질을 확인합니다.','acceptance':'예측 시점 이전 입력만으로 재현 가능한 학습 데이터와 현장 검증셋 확보'}]
    return report

def feasibility(d):
    p=next(x for x in d['domains'] if x['kind']=='production');r=next(x for x in d['domains'] if x['kind']=='recipe')
    b=d['baseline'];c=d['cohorts']
    return [
      {'name':'메뉴·원재료별 1인량 후보','status':'기준선 검증 완료' if b['status']=='evaluated' else '표본 확인 필요','priority':'1순위','target':'과거에 기재된 1인량(g)',
       'evidence':f"생산일지 {p['rows']:,}행 · 반복 집단 {c['groups']:,}개 · 시간순 기준선 평가",
       'method':'메뉴·원재료별 과거 중앙값 → 고객군·식사 구분을 포함한 회귀 모델 후보 비교',
       'need':'승인 배합, 고객군, 1인량 단위 검수, 레시피 개정 이력','evaluation':'시간순 MAE(g)·WAPE·예측 커버리지. 같은 메뉴·원재료 기준선과 비교',
       'verdict':'레시피 초안과 검토 순서에 활용 가능. 과거 기재값의 재현이며 승인 배합 자동 확정은 별도 검증 필요.'},
      {'name':'1인량·투입 기록 이상 후보','status':'탐색 분석 가능','priority':'1순위','target':'평소 분포와 다른 입력 후보(불량 라벨 없음)',
       'evidence':f"동일 메뉴·원재료 {c['eligible_rows']:,}행에서 IQR 후보 {c['outlier_rows']:,}행",
       'method':'집단별 IQR·중앙값 편차 → 특성 확보 후 Isolation Forest 등 후보 비교',
       'need':'오류/정상 검토 라벨, 적용 고객군, 양식과 단위의 변화 이력','evaluation':'담당자 검토 후 유효 후보 비율·후속 조치량. 현재 재현율·정확도 산출 불가',
       'verdict':'후보 추출은 가능. 고객군별 정상 차이를 오탐으로 세지 않도록 검수 필요.'},
      {'name':'원료수불·재고 정합성 점검','status':'규칙 우선','priority':'1순위','target':'장부 수식 불일치와 생산·수불 차이',
       'evidence':f"공통 {d['reconciliation']['common_days']:,}일 · 수량 차이 {d['reconciliation']['counts'].get('수량 차이',0):,}건",
       'method':'전일재고+입고−사용량=재고량, 원재료명·날짜별 대사','need':'공통 품목 코드, 공급사별 단위, 누락/수정 사유',
       'evaluation':'검토 후 정합성 개선율과 미해결 건수','verdict':'확정 산식은 규칙으로 처리. 같은 행의 수식 관계를 학습한 높은 점수는 ML 가치의 증거가 아님.'},
      {'name':'일별 원재료 사용량·발주량 예측','status':'선행 데이터 필요','priority':'2순위','target':'미래 일자의 원재료 사용량(kg)·부족량',
       'evidence':f"생산일지 {p['coverage']['days']:,}개 관측일. 미관측 월 {len(p['coverage']['missing_months'])}개",
       'method':'확정 식수×검수한 1인량 산식 기준선 → 지연 특성·달력 기반 회귀 비교',
       'need':'예측 시점에 알 수 있는 식수·메뉴 계획·고객군·휴무일·발주 리드타임·잔량',
       'evaluation':'날짜 단위 rolling 검증, 관측/미관측 구분, MAE(kg)·WAPE 및 부족/과잉 비용',
       'verdict':'기록량만으로 수요 예측 가능성을 확정하지 않음. 사용량과 실제 수요의 차이 및 누락 날짜부터 확인.'},
      {'name':'조리계획 대비 실제 투입 편차','status':'연결 보완 필요','priority':'2순위','target':'동일 날짜·끼니·메뉴·고객군의 계획 대비 사용량',
       'evidence':f"계획서 {r['rows']:,}행 중 실제 날짜 보유 {r['coverage']['dated_rows']:,}행",
       'method':'계획·실적 키 연결 및 차이 산식 → 편차 원인 회귀 검토','need':'계획 날짜 복원 검수, 공통 메뉴/원재료 코드, 고객군, 레시피 버전',
       'evaluation':'연결률·충돌률·편차의 업무적 설명 가능성','verdict':'현재 계획과 실적을 날짜·고객군으로 안정적으로 연결할 수 없어 예측 과제를 먼저 실행하기 어려움.'},
      {'name':'공정 조건→품질·불량 예측','status':'현재 판단 불가','priority':'이후','target':'LOT·배치별 검사·불량·폐기 결과',
       'evidence':'현재 records 스키마에 설비 센서·배치 LOT·검사 결과 라벨 없음',
       'method':'LOT/배치 기준 공정 특성과 결과 라벨 연결 후 지도학습 검토','need':'온도·시간 등 설비 시계열, LOT 키, 검사·폐기·불량 사유·실측 결과',
       'evaluation':'시간순·LOT 단위 분할, 라벨 신뢰도, 클래스별 재현율과 현장 오탐 비용',
       'verdict':'기록 차이·IQR 후보를 불량 라벨로 대신하지 않음. 현재 데이터로 불량 예측 성능을 주장할 수 없음.'},
      {'name':'영양·알러지 문서 검색','status':'변환·검수 선행','priority':'병행','target':'검수한 문서와 원재료 근거 검색',
       'evidence':f"한글 변환 대기 {next((x['n'] for x in d['statuses'] if x['label']=='conversion_required'),0):,}개. 영양 문서는 시트 미리보기 중심",
       'method':'문서 변환·근거 보존 → 검색 평가 후 RAG 검토','need':'승인 원재료/알러지 기준, 개정·적용일, 문서 청킹·임베딩·평가 질문',
       'evaluation':'근거 검색 평가와 사람의 원문 대조. 의료/안전 판단 자동화 성능으로 표현하지 않음',
       'verdict':'본문 변환과 근거 검수부터 필요. 현재 RAG·임베딩·학습을 수행한 상태가 아님.'}]

def findings(d):
    p,r,s=d['domains'];b=d['baseline'];rec=d['reconciliation'];eq=d['inventory_equation'];patterns=d['menu_patterns']
    covered=rec['counts'].get('일치',0)+rec['counts'].get('수량 차이',0)
    return [
      f"생산일지 {p['rows']:,}행의 날짜는 {p['coverage']['first']}~{p['coverage']['last']}, 관측일 {p['coverage']['days']:,}일입니다. 관측된 원문 메뉴 {p['menus']:,}종은 승인 메뉴 마스터 개수와 다릅니다.",
      f"생산일지 관측 범위 안에 기록이 없는 월이 {len(p['coverage']['missing_months'])}개 있습니다. 해당 월을 수요 0으로 채우면 안 됩니다.",
      f"계획서 {r['rows']:,}행 중 실제 날짜 셀을 연결한 행은 {r['coverage']['dated_rows']:,}행({percent(r['coverage']['dated_rows'],r['rows']):.2f}%)입니다. 계획→실적 ML의 우선 과제는 날짜·고객군 연결입니다.",
      f"5회 이상 반복된 메뉴 {patterns['repeat_menus']:,}종 중 원재료 집합이 항상 같은 메뉴는 {patterns['stable_menus']:,}종입니다. 구성 차이는 고객군·계절·대체 원료의 정상 차이일 수도 있습니다.",
      f"생산·수불을 수치로 비교 가능한 {covered:,}건 중 수량 차이는 {rec['counts'].get('수량 차이',0):,}건입니다. 한쪽만 있는 기록은 이 분모에서 제외하며 오류·불량률로 해석하지 않습니다.",
      f"재고 수식 검증 가능한 {eq['eligible']:,}행 중 ±0.001 kg 밖의 차이는 {eq['difference']:,}행입니다. 장부 캐시의 산술 일치와 실물 재고 정확도는 별개입니다.",
      '품질·불량·잔반 라벨과 설비 LOT 연결이 없어 현재는 승인 배합 후보와 입력 편차 검토가 우선입니다.'
    ]


def summary_lines(d):
    domains={r['kind']:r for r in d['domains']}
    p,r,s=(domains[k] for k in ('production','recipe','stock'))
    b=d['baseline'];patterns=d['menu_patterns'];c=d['cohorts'];rec=d['reconciliation']
    compared=rec['counts'].get('일치',0)+rec['counts'].get('수량 차이',0)
    lines=[
        '이 검토는 니즈푸드 데이터의 분포·빈칸·기간·메뉴별 차이를 살펴보고, 지금 할 수 있는 분석과 ML 적용 전에 필요한 일을 정리한 것입니다.',
        f"생산일지 {p['rows']:,}행, 조리계획서 {r['rows']:,}행, 원료수불부 {s['rows']:,}행을 각각 분석했습니다. 계획·실적·재고 장부의 기록을 같은 의미로 합치지 않습니다.",
        f"생산일지는 {p['coverage']['first']}~{p['coverage']['last']}의 {p['coverage']['days']:,}개 관측일을 포함합니다. 해당 범위에서 기록이 없는 월은 {len(p['coverage']['missing_months'])}개이며, 미생산인지 자료 누락인지는 별도 확인이 필요합니다.",
        f"조리계획서에서 실제 날짜 셀을 연결한 행은 {r['coverage']['dated_rows']:,} / {r['rows']:,}행입니다. 원본에 날짜가 없다는 뜻이 아니라 현재 파서로 확보한 연결 수준입니다.",
        '날짜·메뉴·원재료·고객군·레시피 개정을 맞추기 전에는 계획한 양과 실제 사용량을 같은 작업의 학습 쌍으로 만들기 어렵습니다.',
        f"5회 이상 반복 기록된 메뉴 {patterns['repeat_menus']:,}종 중 원재료 집합이 항상 같은 메뉴는 {patterns['stable_menus']:,}종입니다. 구성 차이에는 고객군·계절·대체 재료의 정상 변동도 포함될 수 있습니다.",
        f"같은 메뉴·원재료의 1인량을 비교할 수 있는 집단은 {c['groups']:,}개, 비교 행은 {c['eligible_rows']:,}행입니다. 표본 20행 이상이며 날짜가 5일 이상인 집단만 사용했습니다.",
        f"이 집단에서 평소 분포와 다른 IQR 검토 후보는 {c['outlier_rows']:,}행입니다. 이는 오류·불량 확정 수가 아니며, 원본과 적용 고객군을 확인할 순서에 활용할 수 있습니다.",
        f"생산·수불이 모두 있는 날짜는 {rec['common_days']:,}일입니다. 숫자로 비교 가능한 {compared:,}건 중 수량 차이는 {rec['counts'].get('수량 차이',0):,}건이며, 한쪽 장부에만 있는 기록은 이 분모와 구분합니다.",
        '재고 산식의 일치는 장부의 계산이 맞는지 확인하는 것입니다. 실물 재고가 정확하다는 뜻은 아니며, 이미 정해진 계산 관계는 ML보다 규칙 점검을 우선합니다.',
    ]
    if b['status']=='evaluated':
        mae=b['pair_metrics']['mae'];coverage=b['coverage_percent']
        lines.extend([
            '1인량 후보를 만드는 방법이 어느 정도 쓸 만한지 보기 위해 메뉴·원재료별 과거 중앙값을 기준선으로 실제 검증했습니다. 학습형 ML 모델을 훈련한 결과는 아닙니다.',
            f"기준선은 {b['train_first']}~{b['train_last']}의 과거 관측 {b['train_n']:,}건으로 만들고, 이후 {b['test_first']}~{b['test_last']}의 관측 {b['test_n']:,}건에서 검증했습니다. 같은 날짜의 기록은 양쪽 집합에 나누지 않았습니다.",
            f"과거 표본이 충분해 예측할 수 있었던 관측은 {b['covered_n']:,}건으로, 전체 검증 관측의 {coverage:.1f}%입니다. 새 메뉴·원재료 조합과 과거 표본이 부족한 관측은 점수 계산에서 제외하되 커버리지 분모에는 포함했습니다.",
            f"예측 가능한 관측에서 평균 절대오차는 {mae:.2f}g입니다. 예측값과 실제 기재값의 차이를 절댓값으로 바꾸어 평균한 수치이며, 전체 메뉴의 오차나 승인 배합의 정확도가 아닙니다." if mae is not None else '예측할 수 있는 검증 관측이 없어 평균 절대오차를 표시하지 않습니다.',
            '기준선 결과는 반복 메뉴의 배합 초안과 검토 순서를 정하는 데 참고할 수 있습니다. 고객군·1인량 단위·레시피 개정·승인 배합을 검수한 뒤 활용 범위를 넓혀야 합니다.'
        ])
    else:
        lines.append('시간순 기준선 검증에 필요한 관측이 부족합니다. 성능 점수나 예측 가능 비율을 추정해서 표시하지 않습니다.')
    lines.extend([
        '지금 우선할 일은 레시피 후보 정리, 같은 메뉴 안의 입력 편차 검토, 규칙에 따른 생산·재고 장부 정합성 점검입니다.',
        '원재료 수요·발주량을 예측하려면 예측 시점에 알 수 있는 확정 식수·메뉴 계획·고객군·운영 달력·재고·리드타임을 추가로 연결해야 합니다.',
        '공정 조건으로 품질·불량을 예측하려면 LOT·배치별 센서 기록과 검사·불량·폐기 결과가 필요합니다. 현재 정형 스키마에는 이 입력과 결과 라벨의 연결이 없습니다.',
        '센서 스트림과 RAG·임베딩은 이 앱에 연결하지 않았습니다. 영양·알러지 문서 검색도 원문 변환·유효 개정 확인·근거 검색 평가부터 필요합니다.',
        '먼저 이름·단위·날짜를 검수하고, 반복 메뉴 기준선을 현장에서 확인한 뒤 식수 기반 소요량과 공정·품질 분석으로 확장하는 순서를 권합니다. 모든 수치는 표시된 분석 스냅샷 기준입니다.'
    ])
    return lines

def render_document(d):
    def table(head,rs):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+escape(str(h))+'</th>' for h in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in row)+'</tr>' for row in rs)+'</tbody></table></div>'
    body='<h1>니즈푸드 데이터 EDA 및 ML 적용가능성 검토</h1><p>생성 '+escape(d['created_at'])+' · 파서 '+escape(d['source_meta']['parser_version'])+' · 분석 스냅샷</p>'
    body+='<p class="note">데이터셋 '+escape(d['source_meta']['dataset_id'])+' · 보고서 버전 '+VERSION+'</p>'
    body+='<section aria-labelledby="summary-title"><h2 id="summary-title">Summary · EDA와 ML 검토 이해하기</h2><ol>'+''.join('<li>'+escape(x)+'</li>' for x in d.get('summary',summary_lines(d)))+'</ol></section>'
    body+='<h2>핵심 발견</h2><ul>'+''.join('<li>'+escape(x)+'</li>' for x in d['findings'])+'</ul>'
    body+='<h2>데이터별 기간과 규모</h2>'+table(['데이터','행','대표 파일','실제 날짜 행','관측 일자 범위'],[[x['label'],f"{x['rows']:,}",x['files'],x['coverage']['dated_rows'],str(x['coverage']['first'])+' ~ '+str(x['coverage']['last'])] for x in d['domains']])
    body+='<h2>수치 분포</h2><p>전체 업무 집단을 모은 탐색용 요약이며 규격·불량 판정에 사용하지 않습니다.</p>'+table(['데이터','항목','단위','적격 n','제외','최소','P05','중앙값','P95','최대'],[[x['label'],f['label'],f['unit'],f['n'],f['excluded'],f['min'],f['p05'],f['median'],f['p95'],f['max']] for x in d['domains'] for f in x['numeric']])
    b=d['baseline'];body+='<h2>시간순 1인량 기준선 검증</h2><p>'+escape(b['split_note'])+'</p>'
    if b['status']=='evaluated':
        body+=table(['항목','결과'],[['과거 구간',b['train_first']+' ~ '+b['train_last']],['검증 구간',b['test_first']+' ~ '+b['test_last']],['검증 관측',b['test_n']],['예측한 검증 관측',b['covered_n']],['커버리지 %',b['coverage_percent']],['메뉴·원재료 기준 MAE(g)',b['pair_metrics']['mae']],['메뉴·원재료 기준 WAPE(%)',b['pair_metrics']['wape']],['원재료만 기준 MAE(g), 동일 평가집단',b['material_metrics_same_test']['mae']]])
    body+='<p><b>학습형 ML 모델은 학습하지 않았습니다.</b> 과거 기재값을 추정하는 통계 기준선의 검증입니다.</p><ul>'+''.join('<li>'+escape(x)+'</li>' for x in b['limitations'])+'</ul>'
    body+='<h2>ML 과제별 검토</h2>'+table(['과제','판정','근거','방법','필요 데이터','평가','결론'],[[x['name'],x['status'],x['evidence'],x['method'],x['need'],x['evaluation'],x['verdict']] for x in d['use_cases']])
    body+='<h2>실행 순서</h2>'+table(['단계','작업','실행 내용','완료 기준'],[[x['stage'],x['title'],x['action'],x['acceptance']] for x in d['roadmap']])
    body+='<h2>해석 한계</h2><ul>'+''.join('<li>'+escape(x)+'</li>' for x in d['limitations'])+'</ul>'
    body+='<h2>평가 방법 참고</h2><ul>'+''.join('<li><a href="'+escape(s['url'],quote=True)+'">'+escape(s['title'])+'</a></li>' for s in d['sources'])+'</ul>'
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>니즈푸드 EDA·ML 검토</title><style>body{font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:1500px;margin:40px auto;padding:24px;color:#213c65;background:#f5f8ff;line-height:1.8}h1,h2{color:#1d4ed8;letter-spacing:-.03em}h2{border-bottom:1px solid #cfddf5;margin-top:38px;padding-bottom:10px}table{width:100%;border-collapse:collapse;background:white;font-size:12px}td,th{padding:12px;text-align:left;border-bottom:1px solid #e0e8f5;min-width:90px;vertical-align:top}th{background:#eaf1ff}.scroll{overflow:auto}.note{font-size:11px;overflow-wrap:anywhere;color:#647a99}a{color:#2563eb}@media print{body{background:white;margin:0;padding:0;font-size:11px}.scroll{overflow:visible}table{font-size:9px}td,th{padding:5px;min-width:0}h2{break-after:avoid}}</style>'+body+'</html>'

def load_report():
    try:d=json.loads(REPORT.read_text())
    except (OSError,ValueError):raise FileNotFoundError('EDA 보고서가 없습니다. Run_EDA.command를 실행하세요.')
    if d.get('report_version')!=VERSION:
        raise ValueError('EDA 보고서 버전이 다릅니다. Run_EDA.command를 실행하세요.')
    with a.connect() as db:current=a.meta(db)
    if any(d.get('source_meta',{}).get(k)!=current.get(k) for k in ('dataset_id','parser_version','created_at')):
        raise ValueError('EDA 보고서와 현재 분석 데이터의 버전이 다릅니다. Run_EDA.command를 실행하세요.')
    d['summary']=summary_lines(d)
    return d

def save():
    d=build_report();REPORT.parent.mkdir(exist_ok=True)
    encoded=json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)
    tmp=REPORT.with_suffix('.tmp');tmp.write_text(encoded);tmp.replace(REPORT)
    html=ROOT/'reports/eda-review.html';html.write_text(render_document(d))
    print(json.dumps({'path':str(REPORT),'version':VERSION,'baseline':{k:v for k,v in d['baseline'].items() if k in ('status','train_n','test_n','coverage_percent','pair_metrics','material_metrics_same_test','train_first','train_last','test_first','test_last')},'findings':d['findings']},ensure_ascii=False,indent=2))
    return d

if __name__=='__main__':save()
