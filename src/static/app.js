'use strict';
const $=s=>document.querySelector(s);
const content=$('#content');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,d=0)=>v===null||v===undefined?'—':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d});
const n=v=>fmt(v,2);
const bytes=v=>v>1048576?fmt(v/1048576,1)+' MB':fmt(v/1024,1)+' KB';
const KIND={production:'생산일지',recipe:'조리계획서',stock:'원료수불부'};
const STATUS={extracted:'구조화 완료',preview_only:'시트 미리보기',conversion_required:'변환 대기',ocr_not_run:'OCR 대기',duplicate:'동일 파일 사본',temporary:'임시파일 제외',template:'양식 제외',indexed:'목록 등록',unrecognized:'양식 확인 필요',empty_template:'입력 행 없음',error:'읽기 오류'};
const TITLE={eda:['데이터 EDA · ML 적용가능성','분포·결측·집단 차이를 살피고, 지금 가능한 분석과 다음에 필요한 데이터를 확인합니다.'],overview:['데이터 통합 현황','흩어진 기록을 연결하고, 다음 판단의 근거를 확인하세요.'],files:['데이터 탐색','원본 파일부터 추출된 행까지, 출처를 따라 살펴보세요.'],recipes:['레시피 · 배합 분석','메뉴별 원재료 구성과 1인량의 변화를 확인하세요.'],production:['생산 · 원료수불 분석','같은 날짜의 원재료 투입과 장부 사용량을 비교합니다.'],quality:['데이터 품질','수치가 비어 있는 기록과 검토가 필요한 원본을 확인하세요.'],connections:['데이터 연결 현황','원본 분석, 실시간 수집, 문서 검색의 연결 상태를 구분합니다.']};
let overview,view='overview',page=1,tab='files',prodTab='reconcile',requestId=0,sourceId='',sheetNext=null,statsRequest=0,sheetRequest=0;
const api=async(path,p={})=>{const r=await fetch('/api/'+path+'?'+new URLSearchParams(p));const d=await r.json();if(!r.ok)throw new Error(d.error||'조회 실패');return d;};
const tag=(text,style='')=>`<span class="tag ${style}">${esc(text)}</span>`;
const state=s=>tag(STATUS[s]||s,['conversion_required','ocr_not_run','unrecognized'].includes(s)?'warn':['temporary','duplicate','template','indexed','preview_only'].includes(s)?'gray':s==='error'?'error':'');
const kpi=(label,value,unit,note,icon='↗')=>`<div class="kpi"><div class="kpi-label">${esc(label)}<i>${icon}</i></div><strong>${typeof value==='string'?esc(value):fmt(value)}<small>${esc(unit)}</small></strong><p>${esc(note)}</p></div>`;
const panel=(title,body,note='',corner='')=>`<section class="panel"><div class="panel-title"><h2>${esc(title)}</h2><small>${esc(corner)}</small></div>${body}${note?`<p class="panel-note">${esc(note)}</p>`:''}</section>`;
const bars=(rs,total=false)=>{let max=Math.max(1,...rs.map(r=>r.n));let sum=rs.reduce((a,r)=>a+r.n,0);return rs.map(r=>`<div class="chart-row"><span title="${esc(r.label)}">${esc(r.label)}</span><div class="track"><div class="fill" style="width:${100*r.n/max}%"></div></div><strong>${fmt(r.n)}${total?` <small>· ${fmt(100*r.n/sum,1)}%</small>`:''}</strong></div>`).join('');};
const table=(heads,rs)=>`<div class="table-wrap"><table class="table"><thead><tr>${heads.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rs.length?rs.map(r=>`<tr>${r.map(c=>`<td>${c??'—'}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${heads.length}" class="empty">조건에 해당하는 기록이 없습니다.</td></tr>`}</tbody></table></div>`;
const sourceButton=(id,text='원본 보기',sheet='',row=1)=>`<button class="link-button" data-source="${esc(id)}" data-source-sheet="${esc(sheet)}" data-source-row="${row}">${esc(text)}</button>`;
const pager=d=>`<div class="pager"><span class="total">총 ${fmt(d.total)}건 · ${fmt(d.size)}건씩 표시</span><button data-page="${d.page-1}" ${d.page<=1?'disabled':''}>← 이전</button><span>${d.page} / ${Math.max(1,Math.ceil(d.total/d.size))}</span><button data-page="${d.page+1}" ${d.page*d.size>=d.total?'disabled':''}>다음 →</button></div>`;
const opts=(arr,first='전체')=>`<option value="">${esc(first)}</option>`+arr.map(x=>`<option value="${esc(x.value??x)}">${esc(x.label??x)}</option>`).join('');
const search=placeholder=>`<label>검색<input type="search" name="q" placeholder="${esc(placeholder)}"></label>`;
const dates=()=>`<label>시작일<input type="date" name="start"></label><label>종료일<input type="date" name="end"></label>`;
const applyButton='<button class="button primary" type="submit">적용</button><button class="button" type="reset">초기화</button>';
const params=()=>Object.fromEntries(new FormData($('#filters')));
const form=(fields)=>`<form class="filters" id="filters">${fields}${applyButton}</form>`;
function monthlyChart(rs){
 const arr=rs.filter(r=>r.kind==='production');const max=Math.max(1,...arr.map(r=>r.n));
 return `<div class="monthly-chart" aria-label="월별 생산일지 추출 행 수">${arr.map((r,i)=>`<div class="month-bar" title="${esc(r.month)}: ${fmt(r.n)}행"><i style="height:${Math.max(1,r.n/max*100)}%"></i>${i%3===0||i===arr.length-1?`<span>${r.month.slice(2)}</span>`:''}</div>`).join('')}</div>`;
}
function renderSummary(title,lines,id){return `<section class="brief-summary" aria-labelledby="${esc(id)}"><div class="eyebrow">SUMMARY</div><h2 id="${esc(id)}">Summary · ${esc(title)}</h2><ol>${lines.map(line=>`<li>${esc(line)}</li>`).join('')}</ol></section>`;}
function renderOverview(){
 const o=overview,kind=k=>o.kinds.find(x=>x.label===k)?.n??0;
 const warn=o.statuses.filter(r=>['conversion_required','ocr_not_run','error','unrecognized'].includes(r.label)).reduce((s,r)=>s+r.n,0);
 content.innerHTML=`${renderSummary('대시보드 이해하기',o.summary,'overview-summary-title')}<div class="kpis">${kpi('원본 데이터 자산',o.files,'개',bytes(o.bytes)+' · 임시파일과 사본 포함','▤')}${kpi('생산일지 원재료 기록',kind('production'),'행',fmt(o.menus)+'개 메뉴 · '+fmt(o.materials)+'종 원재료','▥')}${kpi('조리계획서 원재료 기록',kind('recipe'),'행','계획값 · 생산 실적과 별도 관리','◈')}${kpi('변환 · 검토 대기',warn,'개','한글 문서 · PDF · 읽기 상태 기준','◎')}</div>
 <div class="section-heading"><h2>데이터 자산 개요</h2><p>원본 목록과 정형화한 기록을 구분해 확인합니다.</p></div>
 <div class="grid">${panel('업무별 원본 파일',bars(o.categories,true),'파일은 폴더의 업무 분류에 따라 집계합니다.','FILES BY DOMAIN')}${panel('월별 생산일지 기록',monthlyChart(o.monthly),'생산일자 기준 · 기록이 있는 월만 표시 · 입력 행 수이며 완성된 생산량이 아닙니다.','ROWS / MONTH')}</div>
 <div class="grid equal">${panel('정형 데이터 구성',table(['데이터','원본 대표 파일','추출 기록','상태'],o.kinds.map(r=>[esc(KIND[r.label]),fmt(r.files)+'개',fmt(r.n)+'행',tag('추출 후보')])),'숫자·빈칸과 원문을 보존했습니다. 추출 완료는 검수·승인 완료를 뜻하지 않습니다.')}${panel('데이터 처리 흐름','<div class="mini-flow"><div>01 · 원본 조사<small>파일 해시 · 업무 분류</small></div><div>02 · 표 구조화<small>제목으로 열 위치 식별</small></div><div>03 · 분석 집계<small>메뉴 · 원재료 · 날짜</small></div><div>04 · 근거 확인<small>파일 · 시트 · 원본 행</small></div></div>'+bars(o.statuses.slice(0,4).map(r=>({...r,label:STATUS[r.label]||r.label}))))}</div>
 <div class="callout">${esc(o.dates.first)} ~ ${esc(o.dates.last)}의 생산일자 기록을 분석했습니다. 동일한 내용의 파일은 대표본만 구조화하고, 임시파일·빈 양식은 분리합니다. 파일 수와 추출 행 수를 합산하지 않습니다.</div>`;
}
function renderFiles(){
 content.innerHTML=`<div class="tabs"><button data-file-tab="files" class="${tab==='files'?'active':''}">원본 파일</button><button data-file-tab="records" class="${tab==='records'?'active':''}">추출 데이터</button></div>`+
 (tab==='files'?form(search('파일명 또는 폴더 경로')+`<label>업무 분류<select name="category">${opts(overview.categories.map(r=>r.label))}</select></label><label>처리 상태<select name="status">${opts(overview.statuses.map(r=>({value:r.label,label:STATUS[r.label]||r.label})))}</select></label>`):form(search('메뉴 또는 원재료')+`<label>데이터<select name="kind">${opts(Object.entries(KIND).map(([value,label])=>({value,label})))}</select></label>`+dates()))+'<div id="results" class="panel"></div>';
 bindFilters();loadFiles();
}
async function loadFiles(){
 const id=++requestId;const p={...params(),page};$('#results').innerHTML='<div class="loading">기록을 찾고 있습니다…</div>';
 try{const d=await api(tab,p);if(id!==requestId)return;
 $('#results').innerHTML=tab==='files'?table(['원본 파일','업무','형식 · 크기','처리 상태','근거'],d.rows.map(r=>[`${sourceButton(r.id,r.name)}<small>${esc(r.path)}</small>`,esc(r.category),`${esc(r.ext||'확장자 없음')}<small>${bytes(r.bytes)}</small>`,state(r.status),sourceButton(r.id)]))+pager(d):recordTable(d)+pager(d);
 }catch(e){showError(e,$('#results'));}
}
function recordTable(d){return table(['날짜 · 구분','메뉴 / 원재료','1인량 g','사용량 kg','원본 근거','품질'],d.rows.map(r=>[`${esc(r.work_date||'날짜 미확인')}<small>${esc(KIND[r.kind])} · ${esc(r.meal)}</small>`,`${esc(r.menu)}<small>${esc(r.material)}</small>`,n(r.portion),`${n(r.used)}${r.unit!=='kg'?`<small>원본 단위: ${esc(r.unit||'없음')}</small>`:''}`,`${sourceButton(r.file_id,r.source_name,r.sheet,r.row)}<small>${esc(r.sheet)} · ${r.row}행</small>`,r.issues.length?tag(r.issues[0],'warn'):tag('추출 후보')]))}
function renderRecipes(){
 content.innerHTML=`<div class="callout">생산일지에서 같은 날짜·끼니·메뉴의 원재료 구성을 비교합니다. 구성 일치율은 배합 승인이나 조리 품질 판정이 아닙니다. 조리계획서의 계획값은 데이터 탐색에서 별도로 확인할 수 있습니다.</div>${form(search('메뉴명')+dates())}<div id="recipe-kpis"></div><div class="grid equal"><div class="panel" id="recipe-ranking"></div><div class="panel" id="distribution"><div class="loading">통계 계산 중…</div></div></div><div id="results" class="panel"></div>`;
 bindFilters();loadRecipes();
}
async function loadRecipes(){
 const id=++requestId,p={...params(),page};
 try{const d=await api('recipes',p);if(id!==requestId)return;
 $('#recipe-kpis').innerHTML=`<div class="kpis">${kpi('분석 대상 메뉴',d.total,'종','선택 기간의 생산일지 기준')}${kpi('5회 이상 반복 메뉴',d.repeat_menus,'종','안정성 비교 대상')}${kpi('원재료 구성이 같은 메뉴',d.stable_menus,'종','반복 5회 이상 · 구성 종류 1개')}${kpi('구성 일치 비율',d.repeat_menus?fmt(d.stable_menus/d.repeat_menus*100,1):'—','%',`분모: 반복 메뉴 ${fmt(d.repeat_menus)}종`)}</div>`;
 $('#recipe-ranking').innerHTML=`<div class="panel-title"><h2>자주 기록된 메뉴</h2><small>PRODUCTION RECORDS</small></div>`+bars(d.rows.slice(0,10).map(r=>({label:r.menu,n:r.executions})))+'<p class="note">같은 메뉴가 기록된 날짜·끼니별 원재료 집합 수입니다. 여러 파일에 겹치는 날짜는 제외합니다.</p>';
 $('#results').innerHTML=table(['메뉴','기록 횟수','원재료 구성 종류','최빈 구성 비중','최빈 구성 원재료 수'],d.rows.map(r=>[`<button class="link-button" data-menu="${esc(r.menu)}">${esc(r.menu)}</button>`,fmt(r.executions),fmt(r.variants),fmt(r.mode_share*100,1)+'%',fmt(r.ingredients)+'종']))+pager(d);
 await loadStats();
 }catch(e){showError(e,$('#results'));}
}
async function loadStats(p={}){
 const target=$('#distribution');if(!target)return;
 const req=++statsRequest;try{const d=await api('stats',{...params(),...p});if(view!=='recipes'||req!==statsRequest)return;
 target.innerHTML=`<div class="panel-title"><h2>원재료별 수치 분포</h2><small>단일 메뉴 · 원재료</small></div><form id="stats-form" class="filters"><label>메뉴 · 원재료<select name="pair">${d.pairs.map(r=>`<option value="${esc(JSON.stringify([r.menu,r.material]))}" ${r.menu===d.menu&&r.material===d.material?'selected':''}>${esc(r.menu)} / ${esc(r.material)} (${r.n}행)</option>`).join('')}</select></label><label>분석 항목<select name="field"><option value="portion" ${d.field==='portion'?'selected':''}>1인량 (g)</option><option value="used" ${d.field==='used'?'selected':''}>사용량 (kg)</option></select></label></form>
 <div class="histogram">${d.histogram.map(r=>`<div style="height:${Math.max(1,r.n/Math.max(1,...d.histogram.map(x=>x.n))*100)}%" title="${n(r.low)} ~ ${n(r.high)} ${d.unit}: ${r.n}건"><span>${fmt(r.n)}</span></div>`).join('')}</div><div class="axis"><span>${n(d.min)} ${d.unit}</span><span>${n(d.max)} ${d.unit}</span></div><div class="stats-grid">${[['표본 n',d.n],['중앙값',d.median],['평균',d.mean],['표준편차',d.stdev],['최소',d.min],['Q1',d.q1],['Q3',d.q3],['최대',d.max]].map(([label,v])=>`<div><span>${label}</span><b>${n(v)}</b></div>`).join('')}</div><p class="note">${esc(d.menu)} / ${esc(d.material)} · 제외 ${fmt(d.excluded)}행(빈칸·문자·단위 미확인). 분위수는 선형 보간, 표준편차는 표본 기준. IQR 검토 후보 ${fmt(d.outliers)}건이며 불량 판정이 아닙니다. 선택 목록은 기록 수 상위 200개 조합입니다.</p>`;
 $('#stats-form').addEventListener('change',()=>{const f=new FormData($('#stats-form'));const pair=JSON.parse(f.get('pair')||'[]');loadStats({menu:pair[0]||'',material:pair[1]||'',field:f.get('field')});});
 }catch(e){showError(e,target);}
}
function renderProduction(){
 content.innerHTML=`<div class="tabs"><button data-prod-tab="reconcile" class="${prodTab==='reconcile'?'active':''}">생산 · 수불 대사</button><button data-prod-tab="records" class="${prodTab==='records'?'active':''}">생산 · 수불 원장</button></div>${form(search('원재료명')+dates()+(prodTab==='reconcile'?`<label>대사 상태<select name="status">${opts(['수량 차이','생산에만 기록','수불에만 기록','비교 불가','일치'])}</select></label>`:`<label>원장<select name="kind">${opts([{value:'production',label:'생산일지'},{value:'stock',label:'원료수불부'}])}</select></label>`))}<div id="production-kpis"></div><div id="production-note"></div><div id="results" class="panel"></div>`;
 bindFilters();loadProduction();
}
async function loadProduction(){
 const id=++requestId,p={...params(),page};
 try{
 if(prodTab==='records'){
  const d=await api('records',{...p,kind:p.kind||'production'});if(id!==requestId)return;
  $('#results').innerHTML=d.rows[0]?.kind==='stock'?table(['날짜','원재료 · 공급사','전일재고','입고','사용량','재고량','단위','근거'],d.rows.map(r=>[esc(r.work_date),`${esc(r.material)}<small>${esc(r.supplier)}</small>`,n(r.opening),n(r.incoming),n(r.used),n(r.closing),esc(r.unit||'미확인'),`${sourceButton(r.file_id,r.source_name,r.sheet,r.row)}<small>${esc(r.sheet)} · ${r.row}행</small>`]))+pager(d):recordTable(d)+pager(d);return;
 }
 const d=await api('reconcile',p);if(id!==requestId)return;
 $('#production-kpis').innerHTML=`<div class="kpis">${kpi('두 장부 공통 날짜',d.common_days,'일','같은 날짜의 기록만 비교')}${kpi('사용량 일치',d.counts['일치']||0,'건','허용 차이 ±0.01 kg')}${kpi('수량 차이',d.counts['수량 차이']||0,'건','이름 일치 · 수치 비교 가능')}${kpi('한쪽 장부에만 기록',(d.counts['생산에만 기록']||0)+(d.counts['수불에만 기록']||0),'건','공통 날짜 내 원재료 기준')}</div>`;
 $('#production-note').innerHTML=`<div class="callout warn">${esc(d.basis)} 한쪽 날짜만 있는 ${fmt(d.excluded_days)}일${d.conflict_days?` 및 여러 파일의 기록이 겹치는 ${fmt(d.conflict_days)}일`:''}은 비교에서 제외했습니다. 원재료명은 공백만 정리하며 브랜드·규격을 임의 통합하지 않습니다. 수량 차이는 누락·표기 차이·입력 오류 등의 검토 후보입니다.</div>`;
 $('#results').innerHTML=table(['날짜','원재료','생산 사용량 kg','수불 사용량 kg','차이 kg','상태','원본 근거'],d.rows.map(r=>[esc(r.date),esc(r.material),n(r.production),n(r.stock),n(r.delta),tag(r.status,r.status==='일치'?'':r.status==='비교 불가'?'gray':'warn'),[r.production_source?sourceButton(r.production_source,'생산'):null,r.stock_source?sourceButton(r.stock_source,'수불'):null].filter(Boolean).join(' · ')]))+pager(d);
 }catch(e){showError(e,$('#results'));}
}
async function renderQuality(){
 content.innerHTML='<div class="loading">품질 항목을 집계하고 있습니다…</div>';
 try{const d=await api('quality');if(view!=='quality')return;
 content.innerHTML=`<div class="callout warn">${esc(d.note)} 미입력·문자·수식 캐시 없음은 숫자 0과 구분합니다. 파일 해시가 같아도 실제 업무 중복 여부와는 별개입니다.</div><div class="grid equal">${panel('추출 행의 검토 항목',bars(d.issues.slice(0,12)),'한 행에 여러 검토 항목이 있을 수 있으므로 항목 수를 더해 행 수로 해석하지 않습니다.')}${panel('원본 처리 상태',bars(d.pending.map(r=>({...r,label:STATUS[r.label]||r.label}))),'미리보기는 표준화 완료가 아닙니다. HWP·구형 Excel과 PDF는 변환 또는 OCR이 필요합니다.')}</div>${panel('여러 파일에 기록된 동일 날짜',table(['데이터','기록 날짜','파일 수'],d.overlaps.map(r=>[esc(KIND[r.kind]),esc(r.work_date),fmt(r.files)])),'다른 버전이거나 날짜를 복사했을 수 있습니다. 해당 날짜는 생산·수불 대사에서 제외합니다.')}
 <div style="margin-top:18px">${panel('검토가 필요한 원본 예시',table(['데이터','원재료','검토 항목','셀 근거'],d.examples.slice(0,40).map(r=>[esc(KIND[r.kind]),esc(r.material),esc(JSON.parse(r.issues).join(' · ')),`${sourceButton(r.file_id,r.name,r.sheet,r.row)}<small>${esc(r.sheet)} · ${r.row}행</small>`])),'최대 40개 예시. 전체 원문·추출값은 데이터 탐색과 CSV 내보내기에서 확인하세요.')}</div>`;
 }catch(e){showError(e);}
}
function renderConnections(){
 const o=overview;
 content.innerHTML=`${panel('연결된 데이터와 준비 상태',o.connections.map(r=>`<div class="connection"><div class="connection-icon">${r.label==='원본 파일'?'▤':'⇄'}</div><div><h3>${esc(r.label)}</h3><p>${esc(r.note)}</p></div>${tag(r.status,r.status==='미연결'?'gray':'')}</div>`).join(''))}<div class="grid equal">${panel('분석 데이터의 기준',table(['항목','값'],[['분석 근거','로컬 원본에서 생성한 스냅샷'],['스냅샷 생성',esc(new Date(o.meta.created_at).toLocaleString('ko-KR'))],['데이터셋 ID',`<code>${esc(o.meta.dataset_id)}</code>`],['파서 버전',esc(o.meta.parser_version)],['원본 위치',esc(o.meta.source_root)]]),'파일 해시 기반 ID는 분석 원본 집합을 식별합니다. 원본이 바뀌면 데이터 새로고침을 실행하세요.')}${panel('실제 연결에 필요한 정보','<div class="connection"><div><h3>센서 스트림</h3><p>수집원 ID · 이벤트 ID · 이벤트 시각 · 수신 시각 · 항목 · 값 · 단위 · 품질 상태가 필요합니다.</p></div></div><div class="connection"><div><h3>RAG 문서 검색</h3><p>문서 변환 · 출처를 보존한 청킹 · 임베딩 모델 · 벡터 저장소 · 검색 평가가 필요합니다.</p></div></div>','미연결은 수집량 0 또는 검색 품질 0을 뜻하지 않습니다.')}</div>`;
}
function showError(e,target=content){target.innerHTML=`<div class="error-box">${esc(e.message)}<p>데이터 새로고침 또는 서버 로그에서 상태를 확인할 수 있습니다.</p></div>`;}
function bindFilters(){
 $('#filters').addEventListener('submit',e=>{e.preventDefault();page=1;loadCurrent();});
 $('#filters').addEventListener('reset',()=>{page=1;setTimeout(loadCurrent,0);});
}
function loadCurrent(){if(view==='files')loadFiles();if(view==='recipes')loadRecipes();if(view==='production')loadProduction();}
async function openSource(id,requestedSheet='',requestedRow=1){
 sourceId=id;const dialog=$('#source-dialog');if(!dialog.open)dialog.showModal();$('#source-content').innerHTML='<div class="loading">원본 정보를 불러오는 중…</div>';
 try{const d=await api('source',{id});if(sourceId!==id)return;
 $('#source-title').textContent=d.name;
 $('#source-content').innerHTML=`<p class="source-path">${esc(d.path)}</p><div class="source-meta">${state(d.status)}<span>${bytes(d.bytes)}</span><span>대표본 추출 ${fmt(d.record_count)}행</span><span title="${esc(d.sha256)}">SHA256 ${esc(d.sha256.slice(0,16))}…</span></div>${d.status==='duplicate'?`<div class="callout">동일 파일 대표본: ${sourceButton(d.canonical_id,'대표 원본 보기')}</div>`:''}<div class="source-controls"><a class="button primary" href="/download?id=${esc(id)}">↓ 원본 다운로드</a><a class="button" href="/export?table=records&file_id=${esc(d.canonical_id)}">추출 행 CSV</a>${d.sheets.length?`<label>시트 <select id="source-sheet">${d.sheets.map(s=>`<option>${esc(s.name)}</option>`).join('')}</select></label>`:''}</div>${d.source_changed?'<div class="callout warn">원본 파일이 분석 시점 이후 변경되었습니다. 현재 셀 미리보기와 분석값이 다를 수 있습니다. Refresh_Data.command를 실행해 다시 분석하세요.</div>':''}${d.error?`<div class="callout warn">${esc(d.error)}</div>`:''}<div id="sheet-preview"></div>`;
 if(d.sheets.length){if(requestedSheet&&d.sheets.some(s=>s.name===requestedSheet))$('#source-sheet').value=requestedSheet;$('#source-sheet').addEventListener('change',()=>loadSheet(1));loadSheet(Math.max(1,requestedRow-4));}else{$('#sheet-preview').innerHTML='<div class="empty">이 파일은 셀 미리보기가 없습니다. 원본을 내려받아 확인하세요.</div>';}
 }catch(e){showError(e,$('#source-content'));}
}
async function loadSheet(start){
 const req=++sheetRequest;const target=$('#sheet-preview'),id=sourceId,sheet=$('#source-sheet').value;
 target.innerHTML='<div class="loading">원본 셀을 읽고 있습니다…</div>';
 try{const d=await api('sheet',{id,sheet,start});if(req!==sheetRequest||id!==sourceId||sheet!==$('#source-sheet').value)return;
 const cols=Math.max(1,...d.rows.map(r=>r.cells.length));
 const col=i=>{let s='';for(let x=i+1;x>0;x=Math.floor((x-1)/26))s=String.fromCharCode(65+(x-1)%26)+s;return s;};
 target.innerHTML=`<div class="table-wrap sheet-table">${table(['행',...Array.from({length:cols},(_,i)=>col(i))],d.rows.map(r=>[fmt(r.row),...Array.from({length:cols},(_,i)=>esc(r.cells[i]??''))]))}</div><div class="pager"><span class="total">원본 저장값 · ${start}행부터 · 최대 100행 / 40열</span><button id="sheet-prev" ${start<=1?'disabled':''}>← 이전</button><button id="sheet-next" ${d.next?'':'disabled'}>다음 →</button></div><p class="note">Excel의 마지막 저장값을 표시합니다. 수식 재계산·OCR은 수행하지 않습니다. 빈칸은 숫자 0과 다릅니다.</p>`;
 $('#sheet-prev').onclick=()=>loadSheet(Math.max(1,start-100));$('#sheet-next').onclick=()=>loadSheet(d.next);
 }catch(e){showError(e,target);}
}
content.addEventListener('click',e=>{
 const jump=e.target.closest('[data-eda-scroll]');if(jump){e.preventDefault();document.getElementById(jump.dataset.edaScroll)?.scrollIntoView({behavior:'smooth',block:'start'});return;}
 const pg=e.target.closest('[data-page]');if(pg&&!pg.disabled){page=Number(pg.dataset.page);loadCurrent();}
 const ft=e.target.closest('[data-file-tab]');if(ft){tab=ft.dataset.fileTab;page=1;renderFiles();}
 const pt=e.target.closest('[data-prod-tab]');if(pt){prodTab=pt.dataset.prodTab;page=1;renderProduction();}
 const mn=e.target.closest('[data-menu]');if(mn){loadStatsForMenu(mn.dataset.menu);}
});
async function loadStatsForMenu(menu){const d=await api('stats',{...params(),menu});if(d.material)loadStats({menu,material:d.material});else{const f=$('#filters');f.elements.q.value=menu;page=1;loadRecipes();}}
document.addEventListener('click',e=>{const s=e.target.closest('[data-source]');if(s)openSource(s.dataset.source,s.dataset.sourceSheet||'',Number(s.dataset.sourceRow||1));});
$('#close-dialog').onclick=()=>$('#source-dialog').close();
$('#source-dialog').addEventListener('click',e=>{if(e.target===$('#source-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
$('#export-button').onclick=()=>{if(view==='eda'){window.location.href='/eda-report?format=html';return;}let p={...($('#filters')?params():{}),table:view==='files'?(tab==='files'?'files':'records'):view==='production'&&prodTab==='reconcile'?'reconcile':'records'};if(view==='recipes'){p.table='recipes';}window.location.href='/export?'+new URLSearchParams(p);};
function route(){
 view=location.hash.slice(1)||'overview';if(!TITLE[view])view='overview';page=1;requestId++;
 document.querySelectorAll('[data-view]').forEach(a=>{a.classList.toggle('active',a.dataset.view===view);if(a.dataset.view===view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 $('#page-title').textContent=TITLE[view][0];$('#page-description').textContent=TITLE[view][1];$('#breadcrumb').textContent=document.querySelector(`[data-view="${view}"]`).textContent.trim();
 $('#export-button').hidden=['connections','quality'].includes(view);$('#export-button').textContent=view==='eda'?'↓ 검토 보고서':'↓ CSV 내보내기';
 ({eda:renderEDA,overview:renderOverview,files:renderFiles,recipes:renderRecipes,production:renderProduction,quality:renderQuality,connections:renderConnections})[view]();
}
window.addEventListener('hashchange',()=>{if(overview)route();});
async function init(){try{overview=await api('overview');$('#as-of').textContent='생성 '+new Date(overview.meta.created_at).toLocaleString('ko-KR');$('#dataset').textContent='DATASET '+overview.meta.dataset_id.slice(0,12);route();}catch(e){showError(e);}}
let edaReport=null,edaRequest=0;
function edaSection(id,eyebrow,title,description){return `<div class="eda-section" id="${id}"><div class="eyebrow">${esc(eyebrow)}</div><h2>${esc(title)}</h2><p>${esc(description)}</p></div>`;}
function readinessTag(status){return tag(status,status.includes('완료')||status.includes('가능')?'':status.includes('불가')?'gray':'warn');}
async function renderEDA(){
 const req=++edaRequest;content.innerHTML='<div class="loading">EDA와 ML 검토 보고서를 불러오고 있습니다…</div>';
 try{
 const d=await api('eda');if(view!=='eda'||req!==edaRequest)return;edaReport=d;
 const b=d.baseline,p=d.domains.find(x=>x.kind==='production'),planned=d.domains.find(x=>x.kind==='recipe'),stock=d.domains.find(x=>x.kind==='stock');
 content.innerHTML=`<div class="eda-action-row"><span class="tag">EDA 생성 ${esc(new Date(d.created_at).toLocaleString('ko-KR'))}</span><span class="tag gray">학습형 ML 미수행 · 통계 기준선 평가</span><a class="button" href="/eda-report?format=html">↓ 검토 보고서 HTML</a><a class="button" href="/eda-report?format=json">↓ 분석 JSON</a></div>
 <div class="kpis">${kpi('생산일지 관측 날짜',p.coverage.days,'일',p.coverage.first+' ~ '+p.coverage.last,'▥')}${kpi('생산 기록이 없는 월',p.coverage.missing_months.length,'개월','관측 범위 내 · 미생산 여부 미확인','◫')}${kpi('5회 이상 반복 메뉴',d.menu_patterns.repeat_menus,'종','원재료 구성·배합 검토 대상','◈')}${kpi('시간순 기준선 커버리지',b.coverage_percent===undefined?'—':fmt(b.coverage_percent,1),'%',fmt(b.covered_n||0)+' / '+fmt(b.test_n||0)+' 검증 관측','↗')}</div>
 ${renderSummary('EDA와 ML 검토 이해하기',d.summary,'eda-summary-title')}
 <nav class="eda-nav" aria-label="EDA 보고서 목차"><a href="#eda" data-eda-scroll="eda-assets">데이터·결측</a><a href="#eda" data-eda-scroll="eda-cohorts">메뉴·배합 편차</a><a href="#eda" data-eda-scroll="eda-linkage">장부 연결</a><a href="#eda" data-eda-scroll="eda-baseline">시간순 기준선</a><a href="#eda" data-eda-scroll="eda-feasibility">ML 적용가능성</a><a href="#eda" data-eda-scroll="eda-roadmap">실행 순서</a></nav>
 ${edaSection('eda-assets','01 / DATA READINESS','데이터 범위와 수치 보유율','표준화한 원재료 행 기준입니다. 메뉴명·원재료명은 공백을 정리한 원문 구분이며 승인 마스터의 종류 수가 아닙니다.')}
 ${panel('데이터별 EDA 범위',table(['데이터','대표 파일','추출 행','원문 메뉴','원문 원재료','실제 날짜 행','관측 기간'],d.domains.map(x=>[esc(x.label),fmt(x.files),fmt(x.rows),fmt(x.menus),fmt(x.materials),`${fmt(x.coverage.dated_rows)}<small>${fmt(x.coverage.dated_rows/x.rows*100,2)}%</small>`,`${esc(x.coverage.first||'미확인')}<small>~ ${esc(x.coverage.last||'미확인')}</small>`])),'생산일지·수불부는 셀 날짜, 계획서는 날짜 셀을 명시적으로 찾은 행만 포함합니다. 파일명·주차를 일자로 추정하지 않았습니다.')}
 <div class="grid equal">${panel('필드별 수치 보유율',table(['데이터 · 항목','숫자 보유 / 전체','보유율','단위 검증 후 n'],d.domains.flatMap(x=>x.numeric.map(f=>[`${esc(x.label)} · ${esc(f.label)}<small>${esc(f.unit)}</small>`,`${fmt(f.filled)} / ${fmt(f.rows)}`,fmt(f.fill_percent,2)+'%',fmt(f.eligible)]))),'숫자 보유와 단위가 확인된 적격 값은 다릅니다. 미입력·문자·수식 캐시 없음은 0으로 바꾸지 않습니다.')}
 ${panel('생산일지 월별 관측 범위',`<div class="coverage-grid">${p.coverage.months.map(x=>`<div class="coverage-cell ${x.n?'':'missing'}" title="${esc(x.month)}: ${fmt(x.n)}행"><b>${esc(x.month)}</b><br>${x.n?fmt(x.n)+'행':'기록 없음'}</div>`).join('')}</div><div class="mini-legend"><span>파랑: 추출 기록 있음</span><span>점선: 기록 없는 월</span></div>`,'미관측 월: '+(p.coverage.missing_months.join(', ')||'없음')+'. 휴무·미생산·원본 누락 여부를 구분할 운영 달력은 없습니다.')}</div>
 <div id="eda-numeric" class="panel"></div>
 ${edaSection('eda-cohorts','02 / RECIPE & COHORTS','같은 메뉴·원재료 안에서 배합 편차 보기','모든 메뉴의 1인량을 한데 묶어 이상을 판정하지 않습니다. 동일한 메뉴·원재료 집단을 기준으로 계산합니다.')}
 <div class="grid equal">${panel('원재료 구성이 달라지는 반복 메뉴',table(['메뉴','실행 기록','구성 종류','최빈 구성 비중'],d.variable_menus.slice(0,12).map(r=>[esc(r.menu),fmt(r.executions),fmt(r.variants),fmt(r.mode_share*100,1)+'%'])),'반복 5회 이상 메뉴 중 최빈 구성 비중이 낮은 순입니다. 고객군·계절·대체 재료의 정상 차이일 수 있어 조리 담당자의 검토가 필요합니다.')}
 ${panel('메뉴·원재료별 1인량 검토 집단',`<div class="stats-grid"><div><span>적격 집단</span><b>${fmt(d.cohorts.groups)}개</b></div><div><span>비교 대상</span><b>${fmt(d.cohorts.eligible_rows)}행</b></div><div><span>IQR 검토 후보</span><b>${fmt(d.cohorts.outlier_rows)}행</b></div><div><span>IQR=0 집단</span><b>${fmt(d.cohorts.zero_iqr_groups)}개</b></div></div><p class="eda-method">${esc(d.cohorts.note)}</p>`,'IQR 후보는 전 기간의 탐색 통계입니다. 미래 예측 모델의 정답 라벨이나 적중률로 사용하지 않습니다.')}</div>
 ${panel('상위 반복 집단의 기술통계',table(['메뉴 · 원재료','n · 날짜 수','중앙값 g','Q1 · Q3 g','최소 · 최대 g','표준편차 g','IQR 후보'],d.cohorts.top.map(r=>[`${esc(r.menu)}<small>${esc(r.material)}</small>`,`${fmt(r.n)}<small>${fmt(r.days)}일</small>`,n(r.median),`${n(r.q1)} · ${n(r.q3)}`,`${n(r.min)} · ${n(r.max)}`,n(r.stdev),`${fmt(r.outliers)}${r.zero_iqr?'<small>IQR=0</small>':''}`])),'표본 표준편차, 선형 보간 분위수. 우유 등 단위 해석·고객별 배분 방식이 필요한 값은 별도 검수가 필요합니다.')}
 <div class="eda-panel-gap">${panel('IQR 검토 후보 원본 예시',table(['메뉴 · 원재료','날짜','1인량 g','원본 셀 근거'],d.cohorts.examples.slice(0,12).map(r=>[`${esc(r.menu)}<small>${esc(r.material)}</small>`,esc(r.work_date),n(r.portion),`${sourceButton(r.file_id,'원본 보기',r.sheet,r.row)}<small>${esc(r.sheet)} · ${r.row}행</small>`])),'후보를 눌러 실제 원본 셀을 확인한 후 입력 오류인지 정상 변동인지 구분하세요.')}</div>
 ${edaSection('eda-linkage','03 / LINKAGE & INTEGRITY','생산·수불 연결과 재고 정합성','공통 날짜, 동일한 원재료명, 확인된 kg 단위만 비교합니다. 계획과 실적의 연결은 별도의 검토가 필요합니다.')}
 <div class="grid equal">${panel('생산·수불 대사 상태',bars(Object.entries(d.reconciliation.counts).map(([label,n])=>({label,n}))),`공통 ${fmt(d.reconciliation.common_days)}일. 한쪽 날짜만 있는 ${fmt(d.reconciliation.excluded_days)}일은 제외합니다. 수량 차이는 오류나 불량의 확정 라벨이 아닙니다.`)}
 ${panel('이름 연결과 장부 산식',table(['검토 항목','결과'],[['생산 / 수불 원재료 원문명',`${fmt(d.name_linkage.production_names)} / ${fmt(d.name_linkage.stock_names)}종`],['원문명 완전 일치',fmt(d.name_linkage.names_overlap)+'종'],['생산에만 있는 이름',fmt(d.name_linkage.production_only)+'종'],['수불에만 있는 이름',fmt(d.name_linkage.stock_only)+'종'],['재고 수식 검증 가능한 행',fmt(d.inventory_equation.eligible)+'행'],['재고 수식 차이 > 0.001 kg',fmt(d.inventory_equation.difference)+'행'],['재고 수식 검증 제외',fmt(d.inventory_equation.unknown)+'행']]),'원재료명 일치는 전 기간의 이름 집합 기준으로 날짜별 연결률과 다릅니다. 장부 수식의 일치는 실물 재고 정확도를 보장하지 않습니다.')}</div>
 <div class="callout warn">계획서 실제 날짜 연결은 ${fmt(planned.coverage.dated_rows)} / ${fmt(planned.rows)}행입니다. 메뉴·식재 이름이 같더라도 같은 날짜·끼니·고객군·레시피 개정인지 확인하기 전에는 계획→실적 학습 쌍으로 만들지 않습니다.</div>
 ${edaSection('eda-baseline','04 / TEMPORAL BASELINE','1인량 기준선: 과거로 만들고 이후 기간에서 검증','학습형 ML 모델을 훈련한 결과가 아닙니다. 메뉴·원재료별 과거 중앙값이 이후의 기재값을 얼마나 재현하는지 확인한 통계 기준선입니다.')}
 ${renderBaselineEDA(b)}
 ${edaSection('eda-feasibility','05 / ML FEASIBILITY','ML 과제별 적용가능성','아래 판정은 현재 추출 스키마와 실제 EDA 결과에 근거한 검토 의견입니다. 행 수만으로 적용 가능 여부를 확정하지 않습니다.')}
 <div class="eda-readiness">${d.use_cases.slice(0,3).map(x=>`<article>${readinessTag(x.status)}<h3>${esc(x.name)}</h3><p>${esc(x.verdict)}</p><small>${esc(x.evidence)}</small></article>`).join('')}</div>
 <div class="panel eda-matrix">${table(['과제 · 우선순위','가능성 · 예측 대상','데이터 근거','방법 · 추가 필요 데이터','평가 방법 · 판단'],d.use_cases.map(x=>[`${esc(x.name)}<small>${esc(x.priority)}</small>`,`${readinessTag(x.status)}<small>${esc(x.target)}</small>`,esc(x.evidence),`${esc(x.method)}<small>필요: ${esc(x.need)}</small>`,`${esc(x.evaluation)}<small>${esc(x.verdict)}</small>`]))}</div>
 ${edaSection('eda-roadmap','06 / NEXT STEPS','실행 순서와 다음 검증','현재 가능한 검토 작업부터 시작해, 실제 운영 데이터의 연결과 승인 이력을 확보합니다.')}
 <div class="eda-workflow">${d.roadmap.map(x=>`<article>${tag(x.stage)}<h3>${esc(x.title)}</h3><p>${esc(x.action)}</p><small>완료 기준 · ${esc(x.acceptance)}</small></article>`).join('')}</div>
 <div class="eda-panel-gap">${panel('해석 범위와 재현 방법',`<div class="eda-method"><ul>${d.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p>재생성: 프로젝트의 <b>Run_EDA.command</b> 실행. 원본을 바꾼 경우 <b>Refresh_Data.command</b>로 원본 추출과 EDA를 함께 갱신하세요.</p><p>원본 데이터셋 ${esc(d.source_meta.dataset_id)}<br>추출 파서 ${esc(d.source_meta.parser_version)} · EDA 버전 ${esc(d.report_version)} · 근거: 로컬 SQLite 분석 스냅샷</p></div><div class="eda-footnotes">${d.sources.map(x=>`<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.title)} ↗</a>`).join('')}</div>`,'현재 데이터와 보고서의 원본 집합·파서·생성 시각이 다르면 보고서 조회를 중단하고 재생성을 안내합니다.')}</div>`;
 renderEDANumeric();
 }catch(e){if(req===edaRequest&&view==='eda')showError(e);}
}
function renderBaselineEDA(b){
 if(b.status!=='evaluated')return '<div class="callout warn">시간순 검증에 필요한 관측 날짜가 부족합니다. 기준선 점수를 표시하지 않습니다.</div>';
 return `<div class="kpis">${kpi('검증 기간 적격 관측',b.test_n,'건','예측하지 못한 새 메뉴·소표본 포함')}${kpi('평가된 관측',b.covered_n,'건','커버리지 '+fmt(b.coverage_percent,1)+'%')}${kpi('메뉴·원재료 기준 MAE',b.pair_metrics.mae===null?'—':fmt(b.pair_metrics.mae,2),'g','평가된 '+fmt(b.covered_n)+'건의 평균 절대오차')}${kpi('메뉴·원재료 기준 WAPE',b.pair_metrics.wape===null?'—':fmt(b.pair_metrics.wape,2),'%','절대오차 합 / 실제값 합 × 100')}</div>
 <div class="grid equal">${panel('시간 순서와 평가 분모',table(['구분','내용'],[['과거 구간',`${esc(b.train_first)} ~ ${esc(b.train_last)}`],['검증 구간',`${esc(b.test_first)} ~ ${esc(b.test_last)}`],['과거 / 검증 관측',`${fmt(b.train_n)} / ${fmt(b.test_n)}건`],['기준선 자격',`과거 ${b.minimum_train_observations}관측 이상 · ${b.minimum_train_days}일 이상`],['예측하지 못한 새 조합',fmt(b.unseen_pair_test_n)+'건'],['과거 표본 부족',fmt(b.insufficient_pair_test_n)+'건'],['서로 다른 1인량의 같은 이벤트',fmt(b.ambiguous_events_excluded)+'건 제외'],['중복된 이벤트 행',fmt(b.duplicate_event_rows_collapsed)+'행 통합']]),b.split_note)}
 ${panel('같은 검증 집단에서 기준선 비교',table(['기준선','평가 n','MAE g','WAPE %'],[['메뉴·원재료별 과거 중앙값',fmt(b.pair_metrics.n),n(b.pair_metrics.mae),n(b.pair_metrics.wape)],['원재료별 과거 중앙값',fmt(b.material_metrics_same_test.n),n(b.material_metrics_same_test.mae),n(b.material_metrics_same_test.wape)]]),'두 기준선 모두 메뉴·원재료 기준선이 예측할 수 있는 동일한 관측만 평가했습니다. 전처리·중앙값·자격 판단에 검증 기간의 값을 사용하지 않았습니다.')}</div>
 <div class="callout warn">검증 관측의 ${fmt(b.coverage_percent,1)}%에서만 기준선이 예측했습니다. 나머지 ${fmt(b.test_n-b.covered_n)}건은 점수의 분모에 포함되지 않습니다. 이 점수를 전체 메뉴의 성능이나 승인 배합의 정확도로 해석하지 않습니다.</div>
 ${panel('평가 관측이 많은 메뉴·원재료',table(['메뉴 · 원재료','과거 n','평가 n','예측 중앙값 g','MAE g','WAPE %'],b.groups.slice(0,15).map(r=>[`${esc(r.menu)}<small>${esc(r.material)}</small>`,fmt(r.train_n),fmt(r.n),n(r.prediction),n(r.mae),n(r.wape)])),'평가 관측 수 상위 15개 조합입니다. 전체 점수는 행 가중 평균이므로 잦은 메뉴의 영향이 큽니다.')}
 <div class="eda-panel-gap">${panel('기준선과 차이가 큰 실제 기재값',table(['날짜','메뉴 · 원재료','기재값 g','예측값 g','원본'],b.predictions.slice(0,10).map(r=>[esc(r.date),`${esc(r.menu)}<small>${esc(r.material)}</small>`,n(r.actual),n(r.predicted),`${sourceButton(r.file_id,'셀 확인',r.sheet,r.row)}<small>${esc(r.sheet)} · ${r.row}행</small>`])),'큰 차이가 입력 오류라는 뜻은 아닙니다. 고객군·레시피 개정·정상 대체 여부를 원본과 함께 확인하세요.')}</div>
 <p class="eda-method">${b.limitations.map(esc).join('<br>')}</p>`;
}
function renderEDANumeric(kind='production',field='portion'){
 const d=edaReport.domains.find(x=>x.kind===kind),target=$('#eda-numeric');if(!target)return;
 const f=d.numeric.find(x=>x.field===field)||d.numeric[0],max=Math.max(1,...f.histogram.map(x=>x.n));
 target.innerHTML=`<div class="panel-title"><h2>업무별 수치 분포</h2><small>탐색용 혼합 집단</small></div><form class="eda-form" id="eda-numeric-form"><label>데이터<select name="kind">${edaReport.domains.map(x=>`<option value="${x.kind}" ${x.kind===kind?'selected':''}>${esc(x.label)}</option>`).join('')}</select></label><label>수치 항목<select name="field">${d.numeric.map(x=>`<option value="${x.field}" ${x.field===f.field?'selected':''}>${esc(x.label)} (${esc(x.unit)})</option>`).join('')}</select></label></form>
 <div class="histogram">${f.histogram.map(r=>`<div class="${r.n?'':'zero'}" style="height:${r.n/max*100}%" title="${n(r.low)} ≤ 값 ${r.high===f.max?'≤':'<'} ${n(r.high)} ${f.unit}: ${fmt(r.n)}행"><span>${fmt(r.n)}</span></div>`).join('')}</div><div class="axis"><span>${n(f.min)} ${f.unit}</span><span>${n(f.max)} ${f.unit}</span></div><div class="stats-grid">${[['적격 n',f.n],['제외',f.excluded],['P05',f.p05],['중앙값',f.median],['평균',f.mean],['표준편차',f.stdev],['P95',f.p95],['최대',f.max]].map(([name,value])=>`<div><span>${esc(name)}</span><b>${n(value)}</b></div>`).join('')}</div><p class="note">0값 ${fmt(f.zero)}행 · 음수 ${fmt(f.negative)}행. 각 구간은 왼쪽 포함·오른쪽 제외이며 마지막 구간은 오른쪽도 포함합니다. 메뉴·고객군이 섞인 탐색 통계이므로 이 분포로 이상·불량·규격 적합을 판정하지 않습니다. 결측·비수치·단위 미확인은 제외합니다.</p>`;
 $('#eda-numeric-form').onchange=e=>{const form=$('#eda-numeric-form');renderEDANumeric(form.elements.kind.value,e.target.name==='kind'?'':form.elements.field.value);};
}

init();
