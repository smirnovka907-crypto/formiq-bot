(()=>{
'use strict';
const app=document.getElementById('app'),tg=window.Telegram?.WebApp,token=tg?.initData||'';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const button=(text,cmd,main=false,attrs='')=>`<button type="button" data-cmd="${cmd}" class="${main?'button-main':'button-subtle'}" ${attrs}>${esc(text)}</button>`;
const block=html=>`<section class="surface">${html}</section>`;
const h=()=>`<header class="header"><span class="brand"><span>FORM</span><em>IQ</em></span><button class="profile-open" data-nav="profile" aria-label="Профиль"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3-7 8-7s8 3 8 7"/></svg></button></header>`;
const icon={plan:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',home:'<path d="m6.5 6.5 11 11M4 9l5-5M15 20l5-5M3 7l4-4M17 21l4-4M9 4l-5 5M20 15l-5 5"/>',food:'<path d="M6 3v7a3 3 0 0 0 6 0V3M9 3v18M18 3v18M16 3c4 2 4 8 2 9"/>',progress:'<path d="M4 20h16M5 17l5-6 4 3 5-8"/>'};
const nav=()=>`<nav class="bottom-nav">${[['home','Главная'],['plan','План'],['progress','Прогресс'],['food','Питание']].map(([k,n])=>`<button class="nav-item ${view===k?'active':''}" data-nav="${k}"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icon[k]}</svg><span>${n}</span></button>`).join('')}</nav>`;
const page=(name,body)=>`${h()}<h1 class="title">${esc(name)}</h1>${body}`;
const input=(name,id,type,extra='')=>`<label class="field"><span>${esc(name)}</span><input id="${id}" type="${type}" value="${esc(drafts[id]??'')}" autocomplete="off" ${extra}></label>`;
let state=null,view='home',error='',busy=false,modal='',detail=null,restUntil=0,restFor='',restSkippedKey='',calendarOpen=false,month='',date='',week=0,cardioType='',typesOpen=false,monthMarks=new Set(),dayRows=null,allRows=[],nextOffset=0,historyBusy=false,drafts=Object.create(null),metricEdit=false,profileDraft=null,profileNotice='',staleSetRefresh=false,nutritionAnswer='',nutritionBusy=false;
const ready=()=>!!(state?.agreed&&state?.profile_raw?.goal&&!state?.needs_health_profile&&!state?.error);
const active=()=>!!(state?.workout?.id&&!state.workout.finished);
const nextKey=()=>{const w=state?.workout,c=w?.current;return w&&c?`${w.id}:${c.position}:${c.set_no}`:'';};
const REST_TIMER_KEY='formiq_v5_rest_countdown';
function storeRestTimer(){
 try{
  if(restSkippedKey&&restSkippedKey===nextKey())
   window.sessionStorage?.setItem(REST_TIMER_KEY,JSON.stringify({skippedFor:restSkippedKey}));
  else if(restUntil>Date.now()&&restFor)
   window.sessionStorage?.setItem(REST_TIMER_KEY,JSON.stringify({until:restUntil,for:restFor}));
  else window.sessionStorage?.removeItem(REST_TIMER_KEY);
 }catch(_error){}
}
function restoreRestTimer(){
 const key=nextKey();
 if(!key){restUntil=0;restFor='';restSkippedKey='';storeRestTimer();return}
 try{
  const stored=window.sessionStorage?.getItem(REST_TIMER_KEY);
  if(stored){
   const timer=JSON.parse(stored);
   if(timer.skippedFor===key){restSkippedKey=key;restUntil=0;restFor='';return}
   if(!Object.prototype.hasOwnProperty.call(state?.workout||{},'rest_remaining_seconds')&&
      Number.isSafeInteger(timer.until)&&timer.until>Date.now()&&timer.for===key){
     restUntil=timer.until;restFor=key;return;
   }
  }
 }catch(_error){}
 const remaining=Number(state?.workout?.rest_remaining_seconds||0);
 if(!restSkippedKey&&remaining>0&&Number.isFinite(remaining)){
  restUntil=Date.now()+remaining*1000;restFor=key;
 }else{restUntil=0;restFor=''}
 storeRestTimer();
}
function updateViewportPosition(){
 const activeInput=document.activeElement;
 if(!activeInput||!['reps','weight','cardio-min','cardio-hr','profile-age','profile-height_cm','profile-weight_kg'].includes(activeInput.id))return;
 const card=activeInput.closest?.('.surface');
 if(!card)return;
 const delta=card.getBoundingClientRect().top-(window.visualViewport?.offsetTop||0)-12;
 if(Math.abs(delta)>15)window.scrollBy({top:delta,behavior:'instant'});
}
async function request(action,more={}){
 if(!token)throw Error('Открой FORMIQ через Telegram.');
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),25000);
 try{
 const resp=await fetch('/mini/api',{method:'POST',headers:{'Content-Type':'application/json','X-Formiq-Init':token},credentials:'same-origin',cache:'no-store',signal:controller.signal,body:JSON.stringify({action,...more})});
 const data=await resp.json();if(!resp.ok||data.ok!==true)throw Error(data.error||'Ошибка API');
 return data;
 }finally{clearTimeout(timeout)}
}
async function send(action,more={}){
 if(busy)return null;busy=true;const originalSet=nextKey();
 try{const response=await request(action,more);if(response.data)state=response.data;
  else if(response.patch&&Object.prototype.hasOwnProperty.call(response.patch,'workout'))state.workout=response.patch.workout;
  else if(response.patch?.metrics){state.metrics=response.patch.metrics;if(response.patch.zones)state.zones=response.patch.zones}
  else state=(await request('state')).data;
  if(action==='state')restoreRestTimer();
  if(originalSet!==nextKey()){drafts.reps='';drafts.weight='';restSkippedKey=''}
  error='';return response}
 catch(e){
  const stale=action==='record'&&/Обнови тренировку|Этот подход уже изменился/i.test(String(e.message));
  if(stale){
   try{
    const previous=nextKey();
    state=(await request('state')).data;
    restoreRestTimer();
    if(previous!==nextKey()){drafts.reps='';drafts.weight=''}
    staleSetRefresh=true;
    error='Дневник обновлён. Проверь текущий подход, прежде чем записывать его.';
   }catch(_refreshError){error='Подход изменился. Перезапусти FORMIQ для обновления.'}
  }else error=e.name==='AbortError'?((action==='record'||action==='cardio')?'Ответ сервера не получен. Перед повтором проверь запись в дневнике, чтобы не создать дубль.':'Сервер не отвечает. Попробуй позже.'):e.message;
  return null
 }
 finally{busy=false;draw()}
}
function workout(){
 const w=state.workout,c=w.current;
 let content='';
 if(!c)content=block(`<h2>Все подходы завершены</h2>${button('Завершить тренировку','finish-confirm',true)}`);
 else if(restUntil>Date.now()&&restFor===nextKey()){
 const seconds=Math.ceil((restUntil-Date.now())/1000);
 content=block(`<span class="eyebrow">ОТДЫХ ПО ПРОГРАММЕ</span><div id="rest-count" class="fq-live-rest-number">${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}</div><p>${esc(c.name)}</p>${button('Пропустить отдых','rest-skip')}`);
 }else content=block(`<span class="eyebrow">ТЕКУЩЕЕ УПРАЖНЕНИЕ</span><h2 class="workout-exercise">${esc(c.name)}</h2><p class="subtitle">Подход ${c.set_no} из ${c.set_count} · цель ${c.low}–${c.high} ${c.unit==='reps'?'повт.':c.unit==='sec'?'сек':'мин'}</p>
 ${c.previous?`<p class="fq-live-muted">Прошлый результат: ${esc(c.previous)}</p>`:''}<p class="fq-live-muted">${esc(c.tip||'')}</p>
 <div class="fq-live-grid">${input(c.unit==='reps'?'Повторения':'Время','reps','number','min="1" max="300" inputmode="numeric"')}${c.unit==='sec'?'<span></span>':input('Вес, кг (необяз.)','weight','number','min="0" max="500" step="0.1" inputmode="decimal"')}</div>
 <p class="input-note">Рекомендованный отдых — ${c.rest_seconds||0} секунд. При боли прекрати движение.</p>${button('Подход выполнен','record',true)}
 <div class="fq-live-actions" style="margin-top:10px">${button('Пропустить упражнение','skip-confirm')}${button('Завершить','finish-confirm')}</div>`);
 return page('Тренировка',`<p class="fq-live-banner">Результаты сохраняются в PostgreSQL через защищённый API FORMIQ.</p>${block(`<span class="eyebrow">${esc(w.title||'Занятие')}</span><h2>${w.done||0} из ${w.total||0} подходов</h2>`)}${content}`);
}
function training(){
 if(!ready())return page('Тренировки',block(`<h2>Нужно заполнить анкету</h2><p>Проверь ограничения и согласия в основном FORMIQ.</p><a class="button-main fq-live-onboarding-link" href="/mini/legacy" data-legacy>Открыть анкету</a>${state?.error?`<p class="fq-live-error">${esc(state.error)}</p>`:''}`));
 if(active())return workout();
 const idx='ABCDEFG'.indexOf(state.next_day||''),list=state.plan?.[idx]||[],upcoming=(state.calendar||[]).find(x=>x.status==='planned'&&x.day===state.next_day);
 return page('Тренировки',block(`<span class="eyebrow">БЛИЖАЙШАЯ ТРЕНИРОВКА</span><h2>${esc(state.plan_names?.[idx]||state.goal||'Тренировка')}</h2><p class="subtitle">${esc(upcoming?.date_ru||'По плану')}</p>
 ${list.map(e=>`<div class="exercise"><span class="exercise-name">${esc(e.name)}</span><span class="exercise-reps">${e.sets} × ${e.low}–${e.high}</span></div>`).join('')}${button('Начать тренировку','mood',true)}`)+block(`<h2>Записать кардио</h2><label class="field"><span>Вид кардио</span>${button(cardioType||'Выбрать вид кардио','cardio-types')}</label>
 ${typesOpen?`<div class="fq-live-actions">${['Ходьба','Бег','Велосипед','Плавание','Другое'].map(x=>button(x,'cardio-type',false,`data-type="${x}"`)).join('')}</div>`:''}
 <div class="fq-live-grid" style="margin-top:12px">${input('Время, мин','cardio-min','number','min="1" max="300" inputmode="numeric"')}${input('Средний пульс','cardio-hr','number','min="40" max="220" inputmode="numeric"')}</div>
 <p class="input-note">Вид кардио, длительность и пульс сохраняются в дневнике. Garmin пока не подключён.</p>${button('Сохранить кардио','cardio',true)}`));
}
const isoDate=ru=>{const p=String(ru||'').split('.');return p.length===3?`${p[2]}-${p[1]}-${p[0]}`:''};
const prettyDate=iso=>{const p=String(iso||'').split('-');return p.length===3?`${p[2]}.${p[1]}.${p[0]}`:iso};
const filtered=()=>date?(dayRows??(state?.history||[]).filter(x=>isoDate(x.date)===date)):(state?.history||[]);
const historyRow=x=>`<button type="button" class="button-subtle" data-cmd="detail" data-id="${x.id}" style="display:block;width:100%;text-align:left;margin-top:8px"><strong>${esc(x.title)}</strong><small style="display:block">${esc(x.date)}</small></button>`;
function calendar(){
 if(!month)month=new Date().toISOString().slice(0,7);
 const [year,n]=month.split('-').map(Number),first=new Date(Date.UTC(year,n-1,1)),count=new Date(Date.UTC(year,n,0)).getUTCDate(),padding=(first.getUTCDay()+6)%7;
 const highlighted=new Set([...monthMarks,...(state.history||[]).map(x=>isoDate(x.date))]);
 return `<div class="fq-live-calendar-controls">${button('‹','prev-month')}<strong>${first.toLocaleDateString('ru-RU',{month:'long',year:'numeric',timeZone:'UTC'})}</strong>${button('›','next-month')}</div><div class="fq-live-days">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(x=>`<small>${x}</small>`).join('')}${'<span></span>'.repeat(padding)}${Array.from({length:count},(_,i)=>{const day=`${month}-${String(i+1).padStart(2,'0')}`;return `<button type="button" class="fq-live-date ${highlighted.has(day)?'has-entry':''} ${date===day?'selected':''}" data-date="${day}" aria-label="${prettyDate(day)}">${i+1}</button>`}).join('')}</div>`;
}
async function fetchMonthMarks(){
 const requested=month;
 try{const result=await request('history_month',{month:requested});if(requested===month){monthMarks=new Set(result.dates||[]);partialHistory()}}
 catch(e){error=e.message;draw()}
}
async function loadDay(){
 const requested=date;
 try{const result=await request('history_page',{date:requested,limit:50,offset:0});if(date===requested){dayRows=result.history||[];partialHistory()}}
 catch(e){error=e.message;draw()}
}
async function loadHistoryPage(){
 if(historyBusy||nextOffset===null)return;
 historyBusy=true;const offset=nextOffset,requested=date;
 try{const result=await request('history_page',{offset,limit:30,...(requested?{date:requested}:{})});if(requested===date){allRows.push(...(result.history||[]));nextOffset=result.next_offset;const dlg=document.querySelector('.fq-live-dialog'),position=dlg?.scrollTop||0;draw();const newDlg=document.querySelector('.fq-live-dialog');if(newDlg)newDlg.scrollTop=position}}
 catch(e){error=e.message;draw()}
 finally{historyBusy=false}
}
function history(){
 return `<section class="surface" id="history-root"><div class="fq-live-history-head"><h2>История тренировок</h2>${button('По датам','calendar',false,`aria-expanded="${calendarOpen}"`)}</div>${calendarOpen?calendar():''}
 ${date?`<div class="fq-live-history-head"><strong>${prettyDate(date)}</strong>${button('Сбросить','reset-date')}</div>`:''}${filtered().slice(0,3).map(historyRow).join('')||'<p>За эту дату записей нет.</p>'}${button('Вся история','history-all')}</section>`;
}
function periodLabel(n){
 const start=state?.cycle_start;
 if(start&&/^\d{4}-\d{2}-\d{2}$/.test(start)){
  const d=new Date(start+'T12:00:00Z');
  if(!Number.isNaN(d.getTime())){
   const a=new Date(d.getTime()+(n-1)*7*86400000),b=new Date(a.getTime()+6*86400000);
   return `${prettyDate(a.toISOString().slice(0,10))} — ${prettyDate(b.toISOString().slice(0,10))}`;
  }
 }
 return `Период ${n}`;
}

function planPage(){
 const rows=state?.calendar||[];
 const periods=[1,2,3,4].map(i=>{
  const toggle='<button type="button" class="'+(week===i?'on':'')+'" data-cmd="week" data-week="'+i+'" aria-expanded="'+(week===i)+'"><span class="week-range">'+esc(periodLabel(i))+'</span></button>';
  const dates=rows.filter(r=>r.week===i).map(r=>'<div class="plan-entry"><span><strong>'+esc(r.title)+'</strong><small>'+esc(r.date_ru)+' · '+(r.status==='done'?'Выполнено':'По плану')+'</small></span></div>').join('');
  return '<div class="week-group">'+toggle+(week===i?'<div class="week-details">'+(dates||'<p class="empty">Нет занятий</p>')+'</div>':'')+'</div>';
 });
 return page('Твой план','<p class="intro">Нажми на период — занятия раскроются прямо под ним.</p><section class="week-selector">'+periods.join('')+'</section>');
}
function progress(){
 const stats=state.stats||{},plan=state.calendar||[];
 return page('Прогресс',block(`<h2>Результаты</h2><div class="fq-live-grid"><div><span class="eyebrow">ТРЕНИРОВОК</span><h2>${stats.total||0}</h2></div><div><span class="eyebrow">ПОДХОДОВ</span><h2>${stats.sets||0}</h2></div></div>`)+
 block('<h2>Garmin Connect</h2><p>Синхронизация пока не подключена.</p>')+
 block(`<h2>Тренировочный план</h2><div class="fq-live-plan-grid">${[1,2,3,4].map(i=>button(periodLabel(i),'week',false,`data-week="${i}"`)).join('')}</div>
 ${week?`<div class="fq-live-list">${plan.filter(x=>x.week===week).map(x=>`<div class="fq-live-row"><span>${esc(x.date_ru)} · ${esc(x.title)}</span><small>${x.status==='done'?'Выполнено':'По плану'}</small></div>`).join('')}</div>`:''}`)+history());
}
function food(){
 return page('Питание',
 block(`<h2>Анализ питания</h2><p class="fq-live-muted">Добавь скриншот JPG/PNG или CSV-отчёт из FatSecret. ИИ покажет показатели только если они присутствуют в отчёте.</p>
 <label class="field"><span>Отчёт питания</span><input id="nutrition-file" type="file" accept=".jpg,.jpeg,.png,.csv,image/jpeg,image/png,text/csv"></label>
 <label class="field" style="display:flex;align-items:flex-start;gap:12px;margin-top:12px"><input id="nutrition-consent" type="checkbox" style="width:22px;min-width:22px;height:22px;margin:0"><span>Разрешаю отправить выбранный отчёт в Yandex AI для анализа. Исходный файл не сохраняется в дневнике.</span></label>
 <p class="input-note">Отдельное согласие на использование ИИ требуется в профиле. Автоматическая синхронизация FatSecret пока не подключена.</p>
 <p id="nutrition-error" class="fq-live-error" role="alert"></p>
 ${button(nutritionBusy?'Анализируем...':'Проанализировать','nutrition-analyze',true,nutritionBusy?'disabled':'')}
 ${nutritionAnswer?`<p role="status" class="fq-live-banner" style="white-space:pre-wrap;margin-top:14px">${esc(nutritionAnswer)}</p>`:''}`)
 +block(`<h2>Настройки питания и согласия</h2><p class="fq-live-muted">Остальные функции доступны в прежнем интерфейсе FORMIQ.</p><a href="/mini/legacy" data-legacy class="button-subtle fq-live-onboarding-link">Открыть прежнюю версию</a>`));
}
function profile(){
 const fields=[['age','Возраст, лет','18','100'],['height_cm','Рост, см','100','240'],['weight_kg','Вес, кг','25','300']];
 const names={'goal':'Цель тренировок','level':'Опыт','days':'Дни в неделю','equipment':'Место тренировок','age_group':'Возрастная группа','minutes':'Длительность','clearance':'Ограничения'};
 const labels=Object.entries(state.profile||{}).map(([k,v])=>`<div class="fq-live-row"><span>${esc(names[k]||k)}</span><strong>${esc(v)}</strong></div>`).join('');
 const data=state.metrics||{};
 const measure=metricEdit?`<div class="fq-live-grid">${fields.map(([key,label,min,max])=>`<label class="field"><span>${label}</span><input id="profile-${key}" data-metric="${key}" type="number" inputmode="${key==='age'?'numeric':'decimal'}" min="${min}" max="${max}" step="${key==='age'?'1':'0.1'}" autocomplete="off" placeholder="—" value="${esc(profileDraft?.[key]??'')}"></label>`).join('')}</div>
 <p class="input-note">Изменятся только исправленные значения. История тренировок сохраняется.</p><div class="fq-live-actions" style="margin-top:12px">${button('Сохранить','profile-metrics-save',true)}${button('Отмена','profile-metrics-cancel')}</div>`:
 `<div class="fq-live-list">${fields.map(([key,label])=>`<div class="fq-live-row"><span>${label}</span><strong>${data[key]===null||data[key]===undefined?'—':esc(data[key])}</strong></div>`).join('')}</div>${button('Изменить параметры','profile-metrics-edit')}`;
 return page('Твой профиль',block(`<h2>Анкета</h2>${labels}<a class="button-main fq-live-onboarding-link" href="/mini/legacy" data-legacy>Редактировать цели, расписание и ограничения</a>`)+
 block(`<h2>Параметры</h2>${profileNotice?`<p role="status" class="fq-live-muted">${esc(profileNotice)}</p>`:''}${measure}`)+
 block('<h2>Самочувствие и ограничения</h2><p>Ограничения учитываются программой на сервере. Для их изменения и подтверждения открой анкету.</p>')+
 block(`<h2>Тарифы</h2><p>${esc(state.tier_name||'Тестовый доступ')}</p><p>Оплата не подключена.</p>`)+
 block('<h2>Подключения</h2><p>Garmin Connect · не подключено</p><p>FatSecret · не подключено</p>'));
}
function modalHTML(){
 if(!modal)return '';
 let content='';
 if(modal==='mood')content=`<h2>Самочувствие перед началом</h2><p>Как себя чувствуешь?</p>${button('Хорошо','start-normal',true)}${button('Устал','start-tired')}`;
 if(modal==='finish')content=`<h2>Завершить тренировку?</h2><p>Оставшиеся подходы будут пропущены.</p>${button('Завершить','finish',true)}${button('Продолжить','close')}`;
 if(modal==='skip')content=`<h2>Пропустить упражнение?</h2>${button('Пропустить','skip',true)}${button('Продолжить','close')}`;
 if(modal==='history')content=`<div class="fq-live-topline"><h2>История</h2>${button('Закрыть','close')}</div>${allRows.map(historyRow).join('')||'<p>Записей нет.</p>'}${nextOffset!==null?button('Загрузить ещё','history-more'):''}`;
 if(modal==='detail')content=`<div class="fq-live-topline"><h2>${esc(detail?.title)}</h2>${button('Закрыть','close')}</div><p>${esc(detail?.date)}</p>${(detail?.items||[]).map(x=>`<div class="fq-live-row"><span>${esc(x.name)}</span><strong>${esc(x.result)}</strong></div>`).join('')}`;
 return `<div class="fq-live-overlay"><div class="fq-live-dialog" role="dialog" aria-modal="true">${content}</div></div>`;
}
function draw(){
 if(!token){app.innerHTML=`<main class="view">${page('FORMIQ',block('<h2>Открой из Telegram</h2><p>Для входа необходима авторизация Telegram.</p>'))}</main>`;return}
 if(!state){app.innerHTML=`<main class="view">${h()}${block(`<h2>${error?'Не удалось загрузить дневник':'Загружаем дневник...'}</h2>${error?`<p class="fq-live-error" role="alert">${esc(error)}</p><p>Перезапусти приложение через Telegram.</p>`:''}`)}</main>`;return}
 app.innerHTML=`<main class="view">${error?`<p class="fq-live-error" role="alert">${esc(error)}</p>`:''}${view==='home'?training():view==='plan'?planPage():view==='progress'?progress():view==='food'?food():profile()}</main>${(view==='profile'||!active())?nav():''}${modalHTML()}`;
}
function partialHistory(){const el=document.getElementById('history-root');if(el)el.outerHTML=history();else draw()}
function fail(s){error=s;draw()}
app.addEventListener('input',e=>{if(['reps','weight','cardio-min','cardio-hr'].includes(e.target.id))drafts[e.target.id]=e.target.value;});
app.addEventListener('focusin',e=>{
 if(!['reps','weight','cardio-min','cardio-hr','profile-age','profile-height_cm','profile-weight_kg'].includes(e.target.id))return;
 const field=e.target,card=e.target.closest('.surface');
 if(!card)return;
 const shift=()=>{if(document.activeElement===field)updateViewportPosition()};
 shift();setTimeout(shift,130);setTimeout(shift,320);
});
window.visualViewport?.addEventListener('resize',updateViewportPosition);
window.visualViewport?.addEventListener('scroll',updateViewportPosition);
app.addEventListener('click',async e=>{
 const legacy=e.target.closest('a[data-legacy]');
 if(legacy){
  e.preventDefault();
  window.location.assign('/mini/legacy'+(window.location.hash||''));
  return;
 }
 const element=e.target.closest('button');if(!element||busy)return;
 if(element.dataset.nav){view=element.dataset.nav;error='';draw();window.scrollTo(0,0);return}
 if(element.dataset.date){date=element.dataset.date;dayRows=null;calendarOpen=false;partialHistory();await loadDay();return}
 const cmd=element.dataset.cmd;
 if(cmd==='profile-metrics-edit'){
  profileNotice='';
  profileDraft={};
  for(const name of ['age','height_cm','weight_kg'])profileDraft[name]=state.metrics?.[name]==null?'':String(state.metrics[name]);
  metricEdit=true;draw();return;
 }
 if(cmd==='profile-metrics-cancel'){metricEdit=false;profileDraft=null;error='';draw();return}
 if(cmd==='profile-metrics-save'){
  if(!metricEdit||!profileDraft)return;
  const values=[['age',18,100,true],['height_cm',100,240,false],['weight_kg',25,300,false]],changes={};
  for(const [name,min,max,whole] of values){
    const input=document.getElementById('profile-'+name);
    if(input)profileDraft[name]=input.value;
    const raw=String(profileDraft[name]??'').trim();
    if(!raw){
      if(state.metrics?.[name]!=null){fail('Не оставляй заполненные параметры пустыми.');return}
      continue;
    }
    if(!(whole?/^\d+$/:/^\d+(?:[.,]\d{1,2})?$/).test(raw)){fail('Проверь формат возраста, роста и веса.');return}
    const value=Number(raw.replace(',','.'));
    if(!Number.isFinite(value)||value<min||value>max){fail('Проверь допустимые значения: возраст 18–100, рост 100–240, вес 25–300.');return}
    if(state.metrics?.[name]==null||Number(state.metrics[name])!==value)changes[name]=value;
  }
  if(!Object.keys(changes).length){metricEdit=false;profileDraft=null;draw();return}
  const response=await send('save_metrics',{metrics:changes});
  if(response){metricEdit=false;profileDraft=null;profileNotice='Изменения сохранены в профиле FORMIQ.';draw()}
  return;
 }
 if(cmd==='nutrition-analyze'){
  if(nutritionBusy)return;
  const file=document.getElementById('nutrition-file')?.files?.[0];
  const consent=document.getElementById('nutrition-consent')?.checked===true;
  const alert=document.getElementById('nutrition-error');
  if(!file){if(alert)alert.textContent='Выбери JPG, PNG или CSV-отчёт.';return}
  if(file.size<24||file.size>1500000){if(alert)alert.textContent='Отчёт должен быть не больше 1,5 МБ.';return}
  if(!consent){if(alert)alert.textContent='Подтверди согласие на отправку выбранного отчёта в Yandex AI.';return}
  nutritionBusy=true;error='';draw();
  const data=new FormData();data.append('report',file);data.append('consent','yes');
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),65000);
  try{
   const response=await fetch('/mini/report',{method:'POST',headers:{'X-Formiq-Init':token},
       credentials:'same-origin',cache:'no-store',body:data,signal:abort.signal});
   const result=await response.json();
   if(!response.ok||!result.ok)throw Error(result.error||'Не удалось прочитать отчёт.');
   nutritionAnswer=String(result.answer||'').slice(0,3200);
  }catch(ex){
   error=ex.name==='AbortError'?'Анализ занимает слишком много времени. Попробуй позже.':ex.message;
  }finally{clearTimeout(timer);nutritionBusy=false;draw()}
  return;
 }
 if(cmd==='close'){modal='';draw();return}
 if(cmd==='mood'){modal='mood';draw();return}
 if(cmd==='start-normal'||cmd==='start-tired'){modal='';await send('start',{mood:cmd==='start-normal'?'normal':'tired'});return}
 if(cmd==='record'){
  const val=document.getElementById('reps')?.value.trim()||'',kg=document.getElementById('weight')?.value.trim()||'';
  if(!/^\d+$/.test(val)||Number(val)<1||Number(val)>300){fail('Введи от 1 до 300 повторений или секунд.');return}
  if(kg&&!/^\d+(?:[.,]\d{1,2})?$/.test(kg)){fail('Укажи вес в килограммах.');return}
  const weight=kg?Number(kg.replace(',','.')):null;if(weight!==null&&weight>500){fail('Вес не может превышать 500 кг.');return}
  const prev=state.workout.current,workoutId=state.workout.id;
  staleSetRefresh=false;
  const success=await send('record',{reps:Number(val),...(weight!==null?{weight}:{}),
   expected_workout:workoutId,expected_position:prev.position,expected_set:prev.set_no});
  if(!success){
   if(staleSetRefresh){staleSetRefresh=false;return}
   const repetitions=document.getElementById('reps'),weightInput=document.getElementById('weight');
   if(repetitions)repetitions.value=val;if(weightInput)weightInput.value=kg;
   return
  }
  const remaining=Number(state.workout?.rest_remaining_seconds??prev.rest_seconds??0);
  if(state.workout?.current&&remaining>0){restUntil=Date.now()+remaining*1000;restFor=nextKey();storeRestTimer();draw()}
  else{restUntil=0;restFor='';storeRestTimer()}return;
 }
 if(cmd==='rest-skip'){restSkippedKey=nextKey();restUntil=0;restFor='';storeRestTimer();draw();return}
 if(cmd==='finish-confirm'){modal='finish';draw();return}
 if(cmd==='skip-confirm'){modal='skip';draw();return}
 if(cmd==='finish'){modal='';const response=await send('finish');if(response){view='progress';restUntil=0;restFor='';storeRestTimer()}draw();return}
 if(cmd==='skip'){modal='';await send('skip');return}
 if(cmd==='cardio-types'){typesOpen=!typesOpen;draw();return}
 if(cmd==='cardio-type'){cardioType=element.dataset.type||'';typesOpen=false;draw();return}
 if(cmd==='cardio'){
  if(!cardioType){fail('Сначала выбери вид кардио.');return}
  const m=document.getElementById('cardio-min')?.value.trim()||'',p=document.getElementById('cardio-hr')?.value.trim()||'';
  if(!/^\d+$/.test(m)||Number(m)<1||Number(m)>300){fail('Время кардио от 1 до 300 минут.');return}
  if(p&&(!/^\d+$/.test(p)||Number(p)<40||Number(p)>220)){fail('Средний пульс 40–220 или пустое поле.');return}
  const saved=await send('cardio',{minutes:Number(m),avg_hr:p?Number(p):null,type:cardioType});
  if(saved){cardioType='';typesOpen=false;drafts['cardio-min']='';drafts['cardio-hr']='';draw()}
  else{const minutes=document.getElementById('cardio-min'),heartrate=document.getElementById('cardio-hr');if(minutes)minutes.value=m;if(heartrate)heartrate.value=p}
  return;
 }
 if(cmd==='week'){week=week===Number(element.dataset.week)?0:Number(element.dataset.week);draw();return}
 if(cmd==='calendar'){calendarOpen=!calendarOpen;month=date.slice(0,7)||new Date().toISOString().slice(0,7);monthMarks=new Set();partialHistory();if(calendarOpen)await fetchMonthMarks();return}
 if(cmd==='prev-month'||cmd==='next-month'){const [y,m]=month.split('-').map(Number);month=new Date(Date.UTC(y,m-1+(cmd==='prev-month'?-1:1),1)).toISOString().slice(0,7);monthMarks=new Set();partialHistory();await fetchMonthMarks();return}
 if(cmd==='reset-date'){date='';dayRows=null;calendarOpen=false;partialHistory();return}
 if(cmd==='history-all'){modal='history';allRows=[];nextOffset=0;draw();await loadHistoryPage();return}
 if(cmd==='history-more'){await loadHistoryPage();return}
 if(cmd==='detail'){const id=Number(element.dataset.id);if(!Number.isSafeInteger(id))return;const result=await send('detail',{id});if(result){detail=result.detail;modal='detail';draw()}return}
});
setInterval(()=>{const element=document.getElementById('rest-count');if(!element)return;const seconds=Math.max(0,Math.ceil((restUntil-Date.now())/1000));if(!seconds){restUntil=0;restFor='';storeRestTimer();draw();return}element.textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`},500);
function syncTelegramInsets(){
 const safe=tg?.safeAreaInset||{},content=tg?.contentSafeAreaInset||{};
 for(const side of ['top','bottom']){
  const inset=Math.max(0,Number(safe[side])||0,Number(content[side])||0);
  document.documentElement?.style?.setProperty('--fq-content-safe-'+side,Math.min(inset,180)+'px');
 }
}
if(token){
 try{
  tg.ready();tg.expand();syncTelegramInsets();
  if(typeof tg.onEvent==='function'){
   tg.onEvent('safeAreaChanged',syncTelegramInsets);
   tg.onEvent('contentSafeAreaChanged',syncTelegramInsets);
   tg.onEvent('fullscreenChanged',syncTelegramInsets);
  }
  if(typeof tg.requestFullscreen==='function'&&
     (typeof tg.isVersionAtLeast!=='function'||tg.isVersionAtLeast('8.0')))tg.requestFullscreen();
 }catch(_e){/* Older Telegram clients stay expanded. */}
 send('state');
}else draw();
})();