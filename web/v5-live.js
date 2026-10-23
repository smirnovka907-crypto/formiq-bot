(()=>{
'use strict';
const app=document.getElementById('app'),tg=window.Telegram?.WebApp,token=tg?.initData||'';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const button=(text,cmd,main=false,attrs='')=>`<button type="button" data-cmd="${cmd}" class="${main?'button-main':'button-subtle'}" ${attrs}>${esc(text)}</button>`;
const block=html=>`<section class="surface">${html}</section>`;
const h=()=>`<header class="header"><span class="brand"><span>FORM</span><em>IQ</em></span><button class="profile-open" data-nav="profile" aria-label="Профиль"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3-7 8-7s8 3 8 7"/></svg></button></header>`;
const nav=()=>`<nav class="bottom-nav">${[['home','Тренировки','⚒'],['food','Питание','♧'],['progress','Прогресс','↗']].map(([k,n,i])=>`<button class="nav-item ${view===k?'active':''}" data-nav="${k}"><span aria-hidden="true" style="font-size:24px">${i}</span><span>${n}</span></button>`).join('')}</nav>`;
const page=(name,body)=>`${h()}<h1 class="title">${esc(name)}</h1>${body}`;
const input=(name,id,type,extra='')=>`<label class="field"><span>${esc(name)}</span><input id="${id}" type="${type}" value="" autocomplete="off" ${extra}></label>`;
let state=null,view='home',error='',busy=false,modal='',detail=null,restUntil=0,restFor='',calendarOpen=false,month='',date='',week=0,cardioType='',typesOpen=false;
const ready=()=>!!(state?.agreed&&state?.profile_raw?.goal&&!state?.needs_health_profile&&!state?.error);
const active=()=>!!(state?.workout?.id&&!state.workout.finished);
const nextKey=()=>{const w=state?.workout,c=w?.current;return w&&c?`${w.id}:${c.position}:${c.set_no}`:''};
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
 if(busy)return null;busy=true;
 try{const response=await request(action,more);if(response.data)state=response.data;else if(response.patch&&Object.prototype.hasOwnProperty.call(response.patch,'workout'))state.workout=response.patch.workout;else state=(await request('state')).data;error='';return response}
 catch(e){error=e.name==='AbortError'?'Сервер не отвечает. Попробуй позже.':e.message;return null}
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
 if(!ready())return page('Тренировки',block(`<h2>Нужно заполнить анкету</h2><p>Проверь ограничения и согласия в основном FORMIQ.</p><a class="button-main fq-live-onboarding-link" href="/mini">Открыть анкету</a>${state?.error?`<p class="fq-live-error">${esc(state.error)}</p>`:''}`));
 if(active())return workout();
 const idx='ABCDEFG'.indexOf(state.next_day||''),list=state.plan?.[idx]||[],upcoming=(state.calendar||[]).find(x=>x.status==='planned'&&x.day===state.next_day);
 return page('Тренировки',block(`<span class="eyebrow">БЛИЖАЙШАЯ ТРЕНИРОВКА</span><h2>${esc(state.plan_names?.[idx]||state.goal||'Тренировка')}</h2><p class="subtitle">${esc(upcoming?.date_ru||'По плану')}</p>
 ${list.map(e=>`<div class="exercise"><span class="exercise-name">${esc(e.name)}</span><span class="exercise-reps">${e.sets} × ${e.low}–${e.high}</span></div>`).join('')}${button('Начать тренировку','mood',true)}`)+block(`<h2>Записать кардио</h2><label class="field"><span>Вид кардио</span>${button(cardioType||'Выбрать вид кардио','cardio-types')}</label>
 ${typesOpen?`<div class="fq-live-actions">${['Ходьба','Бег','Велосипед','Плавание','Другое'].map(x=>button(x,'cardio-type',false,`data-type="${x}"`)).join('')}</div>`:''}
 <div class="fq-live-grid" style="margin-top:12px">${input('Время, мин','cardio-min','number','min="1" max="300" inputmode="numeric"')}${input('Средний пульс','cardio-hr','number','min="40" max="220" inputmode="numeric"')}</div>
 <p class="input-note">Сервер пока сохраняет только время и пульс, но не название вида кардио. Garmin не подключён.</p>${button('Сохранить кардио','cardio',true)}`));
}
const isoDate=ru=>{const p=String(ru||'').split('.');return p.length===3?`${p[2]}-${p[1]}-${p[0]}`:''};
const prettyDate=iso=>{const p=String(iso||'').split('-');return p.length===3?`${p[2]}.${p[1]}.${p[0]}`:iso};
const filtered=()=>((state?.history)||[]).filter(x=>!date||isoDate(x.date)===date);
const historyRow=x=>`<button type="button" class="button-subtle" data-cmd="detail" data-id="${x.id}" style="display:block;width:100%;text-align:left;margin-top:8px"><strong>${esc(x.title)}</strong><small style="display:block">${esc(x.date)}</small></button>`;
function calendar(){
 if(!month)month=new Date().toISOString().slice(0,7);
 const [year,n]=month.split('-').map(Number),first=new Date(Date.UTC(year,n-1,1)),count=new Date(Date.UTC(year,n,0)).getUTCDate(),padding=(first.getUTCDay()+6)%7;
 const highlighted=new Set((state.history||[]).map(x=>isoDate(x.date)));
 return `<div class="fq-live-calendar-controls">${button('‹','prev-month')}<strong>${first.toLocaleDateString('ru-RU',{month:'long',year:'numeric',timeZone:'UTC'})}</strong>${button('›','next-month')}</div><div class="fq-live-days">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(x=>`<small>${x}</small>`).join('')}${'<span></span>'.repeat(padding)}${Array.from({length:count},(_,i)=>{const day=`${month}-${String(i+1).padStart(2,'0')}`;return `<button type="button" class="fq-live-date ${highlighted.has(day)?'has-entry':''} ${date===day?'selected':''}" data-date="${day}" aria-label="${prettyDate(day)}">${i+1}</button>`}).join('')}</div>`;
}
function history(){
 return `<section class="surface" id="history-root"><div class="fq-live-history-head"><h2>История тренировок</h2>${button('По датам','calendar',false,`aria-expanded="${calendarOpen}"`)}</div>${calendarOpen?calendar():''}
 ${date?`<div class="fq-live-history-head"><strong>${prettyDate(date)}</strong>${button('Сбросить','reset-date')}</div>`:''}${filtered().slice(0,3).map(historyRow).join('')||'<p>За эту дату записей нет.</p>'}${button('Вся история','history-all')}</section>`;
}
function progress(){
 const stats=state.stats||{},plan=state.calendar||[];
 return page('Прогресс',block(`<h2>Результаты</h2><div class="fq-live-grid"><div><span class="eyebrow">ТРЕНИРОВОК</span><h2>${stats.total||0}</h2></div><div><span class="eyebrow">ПОДХОДОВ</span><h2>${stats.sets||0}</h2></div></div>`)+
 block('<h2>Garmin Connect</h2><p>Синхронизация пока не подключена.</p>')+
 block(`<h2>Тренировочный план</h2><div class="fq-live-plan-grid">${[1,2,3,4].map(i=>button(`Период ${i}`,'week',false,`data-week="${i}"`)).join('')}</div>
 ${week?`<div class="fq-live-list">${plan.filter(x=>x.week===week).map(x=>`<div class="fq-live-row"><span>${esc(x.date_ru)} · ${esc(x.title)}</span><small>${x.status==='done'?'Выполнено':'По плану'}</small></div>`).join('')}</div>`:''}`)+history());
}
function food(){return page('Питание',block('<h2>Питание</h2><p>Пока доступно через прежний серверный модуль.</p><a class="button-main fq-live-onboarding-link" href="/mini">Открыть питание FORMIQ</a>'))}
function profile(){
 return page('Твой профиль',block(`<h2>Анкета</h2>${Object.entries(state.profile||{}).map(([k,v])=>`<div class="fq-live-row"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}<a class="button-main fq-live-onboarding-link" href="/mini">Редактировать анкету</a>`)+
 block('<h2>Самочувствие и ограничения</h2><p>Учитываются серверной программой.</p>')+
 block(`<h2>Тарифы</h2><p>${esc(state.tier_name||'Тестовый доступ')}</p><p>Оплата не подключена.</p>`)+
 block('<h2>Подключения</h2><p>Garmin Connect · не подключено</p><p>FatSecret · не подключено</p>'));
}
function modalHTML(){
 if(!modal)return '';
 let content='';
 if(modal==='mood')content=`<h2>Самочувствие перед началом</h2><p>Как себя чувствуешь?</p>${button('Хорошо','start-normal',true)}${button('Устал','start-tired')}`;
 if(modal==='finish')content=`<h2>Завершить тренировку?</h2><p>Оставшиеся подходы будут пропущены.</p>${button('Завершить','finish',true)}${button('Продолжить','close')}`;
 if(modal==='skip')content=`<h2>Пропустить упражнение?</h2>${button('Пропустить','skip',true)}${button('Продолжить','close')}`;
 if(modal==='history')content=`<div class="fq-live-topline"><h2>История</h2>${button('Закрыть','close')}</div>${filtered().map(historyRow).join('')}`;
 if(modal==='detail')content=`<div class="fq-live-topline"><h2>${esc(detail?.title)}</h2>${button('Закрыть','close')}</div><p>${esc(detail?.date)}</p>${(detail?.items||[]).map(x=>`<div class="fq-live-row"><span>${esc(x.name)}</span><strong>${esc(x.result)}</strong></div>`).join('')}`;
 return `<div class="fq-live-overlay"><div class="fq-live-dialog" role="dialog" aria-modal="true">${content}</div></div>`;
}
function draw(){
 if(!token){app.innerHTML=`<main class="view">${page('FORMIQ',block('<h2>Открой из Telegram</h2><p>Для входа необходима авторизация Telegram.</p>'))}</main>`;return}
 if(!state){app.innerHTML=`<main class="view">${h()}${block(`<h2>${error?'Не удалось загрузить дневник':'Загружаем дневник...'}</h2>${error?`<p class="fq-live-error" role="alert">${esc(error)}</p><p>Перезапусти приложение через Telegram.</p>`:''}`)}</main>`;return}
 app.innerHTML=`<main class="view">${error?`<p class="fq-live-error" role="alert">${esc(error)}</p>`:''}${view==='home'?training():view==='progress'?progress():view==='food'?food():profile()}</main>${view!=='profile'&&!active()?nav():''}${modalHTML()}`;
}
function partialHistory(){const el=document.getElementById('history-root');if(el)el.outerHTML=history();else draw()}
function fail(s){error=s;draw()}
app.addEventListener('focusin',e=>{
 if(!['reps','weight','cardio-min','cardio-hr'].includes(e.target.id))return;
 const field=e.target,card=e.target.closest('.surface');
 if(!card)return;
 const shift=()=>{if(document.activeElement!==field)return;const diff=card.getBoundingClientRect().top-(window.visualViewport?.offsetTop||0)-12;if(Math.abs(diff)>15)window.scrollBy({top:diff,behavior:'instant'})};
 shift();setTimeout(shift,130);setTimeout(shift,320);
});
app.addEventListener('click',async e=>{
 const element=e.target.closest('button');if(!element||busy)return;
 if(element.dataset.nav){view=element.dataset.nav;error='';draw();window.scrollTo(0,0);return}
 if(element.dataset.date){date=element.dataset.date;calendarOpen=false;partialHistory();return}
 const cmd=element.dataset.cmd;
 if(cmd==='close'){modal='';draw();return}
 if(cmd==='mood'){modal='mood';draw();return}
 if(cmd==='start-normal'||cmd==='start-tired'){modal='';await send('start',{mood:cmd==='start-normal'?'normal':'tired'});return}
 if(cmd==='record'){
  const val=document.getElementById('reps')?.value.trim()||'',kg=document.getElementById('weight')?.value.trim()||'';
  if(!/^\\d+$/.test(val)||Number(val)<1||Number(val)>300){fail('Введи от 1 до 300 повторений или секунд.');return}
  if(kg&&!/^\\d+(?:[.,]\\d{1,2})?$/.test(kg)){fail('Укажи вес в килограммах.');return}
  const weight=kg?Number(kg.replace(',','.')):null;if(weight!==null&&weight>500){fail('Вес не может превышать 500 кг.');return}
  const prev=state.workout.current,success=await send('record',{reps:Number(val),...(weight!==null?{weight}:{})});
  if(success&&state.workout?.current&&Number(prev.rest_seconds)>0){restUntil=Date.now()+prev.rest_seconds*1000;restFor=nextKey();draw()}return;
 }
 if(cmd==='rest-skip'){restUntil=0;restFor='';draw();return}
 if(cmd==='finish-confirm'){modal='finish';draw();return}
 if(cmd==='skip-confirm'){modal='skip';draw();return}
 if(cmd==='finish'){modal='';const response=await send('finish');if(response){view='progress';restUntil=0;restFor=''}draw();return}
 if(cmd==='skip'){modal='';await send('skip');return}
 if(cmd==='cardio-types'){typesOpen=!typesOpen;draw();return}
 if(cmd==='cardio-type'){cardioType=element.dataset.type||'';typesOpen=false;draw();return}
 if(cmd==='cardio'){
  const m=document.getElementById('cardio-min')?.value.trim()||'',p=document.getElementById('cardio-hr')?.value.trim()||'';
  if(!/^\\d+$/.test(m)||Number(m)<1||Number(m)>300){fail('Время кардио от 1 до 300 минут.');return}
  if(p&&(!/^\\d+$/.test(p)||Number(p)<40||Number(p)>220)){fail('Средний пульс 40–220 или пустое поле.');return}
  if(await send('cardio',{minutes:Number(m),avg_hr:p?Number(p):null})){cardioType='';typesOpen=false}return;
 }
 if(cmd==='week'){week=week===Number(element.dataset.week)?0:Number(element.dataset.week);draw();return}
 if(cmd==='calendar'){calendarOpen=!calendarOpen;month=date.slice(0,7)||new Date().toISOString().slice(0,7);partialHistory();return}
 if(cmd==='prev-month'||cmd==='next-month'){const [y,m]=month.split('-').map(Number);month=new Date(Date.UTC(y,m-1+(cmd==='prev-month'?-1:1),1)).toISOString().slice(0,7);partialHistory();return}
 if(cmd==='reset-date'){date='';calendarOpen=false;partialHistory();return}
 if(cmd==='history-all'){modal='history';draw();return}
 if(cmd==='detail'){const id=Number(element.dataset.id);if(!Number.isSafeInteger(id))return;const result=await send('detail',{id});if(result){detail=result.detail;modal='detail';draw()}return}
});
setInterval(()=>{const element=document.getElementById('rest-count');if(!element)return;const seconds=Math.max(0,Math.ceil((restUntil-Date.now())/1000));if(!seconds){restUntil=0;restFor='';draw();return}element.textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`},500);
if(token){try{tg.ready();tg.expand()}catch(e){}send('state')}else draw();
})();