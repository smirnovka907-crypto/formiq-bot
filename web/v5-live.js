(()=>{
'use strict';
const app=document.getElementById('app'),tg=window.Telegram?.WebApp,token=tg?.initData||'';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const button=(text,cmd,main=false,attrs='')=>`<button type="button" data-cmd="${cmd}" class="${main?'button-main':'button-subtle'}" ${attrs}>${esc(text)}</button>`;
const block=html=>`<section class="surface">${html}</section>`;
const h=()=>`<header class="header"><span class="brand"><span>FORM</span><em>IQ</em></span><button class="profile-open" data-nav="profile" aria-label="Профиль" ${onboardOpen||view==='profile'||!ready()?'style="display:none"':''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3-7 8-7s8 3 8 7"/></svg></button></header>`;
const icon={plan:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',home:'<path d="m6.5 6.5 11 11M4 9l5-5M15 20l5-5M3 7l4-4M17 21l4-4M9 4l-5 5M20 15l-5 5"/>',food:'<path d="M6 3v7a3 3 0 0 0 6 0V3M9 3v18M18 3v18M16 3c4 2 4 8 2 9"/>',progress:'<path d="M4 20h16M5 17l5-6 4 3 5-8"/>'};
const nav=()=>`<nav class="bottom-nav">${[['home','Тренировки'],['food','Питание'],['progress','Прогресс']].map(([k,n])=>`<button class="nav-item ${(view===k||(view==='plan'&&k==='home'))?'active':''}" data-nav="${k}"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icon[k]}</svg><span>${n}</span></button>`).join('')}</nav>`;
const page=(name,body)=>`${h()}<h1 class="title">${esc(name)}</h1>${body}`;
const input=(name,id,type,extra='')=>`<label class="field"><span>${esc(name)}</span><input id="${id}" type="${type}" value="${esc(drafts[id]??'')}" autocomplete="off" ${extra}></label>`;
let state=null,view='home',error='',busy=false,modal='',detail=null,restUntil=0,restFor='',restSkippedKey='',calendarOpen=false,month='',date='',week=0,cardioType='',typesOpen=false,monthMarks=new Set(),dayRows=null,allRows=[],nextOffset=0,historyBusy=false,drafts=Object.create(null),metricEdit=false,profileDraft=null,profileNotice='',staleSetRefresh=false,nutritionAnswer='',nutritionBusy=false,progressSeries=null,progressLoading=false,progressError='',progressSelected='';
const ready=()=>!!(state?.agreed&&state?.profile_raw?.goal&&state?.metrics?.age&&state?.metrics?.height_cm&&state?.metrics?.weight_kg&&!state?.needs_health_profile);
// Server-side safety warnings prevent unsafe sessions, not access to the app.
const weekdayNames=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const deviceZone=()=>{try{return Intl.DateTimeFormat().resolvedOptions().timeZone||'Europe/Moscow'}catch(_e){return 'Europe/Moscow'}};
function localClock(){const now=new Date();try{const p=new Intl.DateTimeFormat('en-GB',{timeZone:state?.metrics?.timezone||deviceZone(),year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'}).formatToParts(now);const val=k=>p.find(x=>x.type===k)?.value||'';return {hour:Number(val('hour')),date:val('year')+'-'+val('month')+'-'+val('day')}}catch(_e){return {hour:now.getHours(),date:now.toISOString().slice(0,10)}}}
function allTimezones(){return [...new Set(['Europe/Moscow','Europe/Samara','Asia/Yekaterinburg','Asia/Novosibirsk','Asia/Vladivostok',...(typeof Intl.supportedValuesOf==='function'?Intl.supportedValuesOf('timeZone'):[]),onboard?.timezone,deviceZone()].filter(Boolean))].sort()}

let onboardOpen=false,onboard=null,onboardErrors={};
let periodEntries=null,periodPrediction=null,periodError='',periodDraft={start:'',end:''},periodEditing=null,periodBusy=false,periodMonth='';
let aiTrainingTip='',aiNutritionTip='',aiTipBusy=false,feedbackNotice='',feedbackError='';
const onboardChoices={
 goal:[['Похудеть','loss'],['Мышцы и сила','muscle'],['Выносливость','endurance'],['Поддерживать форму','general']],
 level:[['Новичок','beginner'],['Иногда тренируюсь','some'],['Регулярно тренируюсь','experienced']],
 equipment:[['Дома','home'],['В тренажёрном зале','gym']],
 minutes:Array.from({length:11},(_,i)=>[String(20+10*i)+' мин',String(20+10*i)])
};
const onboardRegions=[['hip','Тазобедренный сустав'],['knee','Колени'],['back','Поясница и спина'],['shoulder','Плечи'],['wrist','Запястья'],['ankle','Голеностоп'],['neck','Шея'],['heart','Сердечно-сосудистая система'],['breathing','Дыхательная система'],['other','Другое']];
function initOnboard(){
 if(onboard)return;
 const p=state?.profile_raw||{},m=state?.metrics||{},health=state?.health_profile||{};
 const chosen=Array.isArray(p.weekdays)?p.weekdays.filter(d=>Number.isInteger(d)&&d>=0&&d<=6):[];
 const oldMinutes=Number(p.minutes)||40;
 onboard={goal:p.goal||'general',level:p.level||'beginner',
  weekdays:[...new Set(chosen)].sort((a,b)=>a-b),
  equipment:p.equipment==='gym'?'gym':'home',
  minutes:String(Math.max(20,Math.min(120,Math.round(oldMinutes/10)*10))),
  age:String(m.age??''),height_cm:String(m.height_cm??''),weight_kg:String(m.weight_kg??''),
  equipment_description:state?.equipment_description||'',sex:['male','female'].includes(m.sex)?m.sex:'',timezone:m.timezone||deviceZone(),timezoneConfirmed:false,
  description:state?.health_description||'',healthStorageConsent:!!state?.health_description,
  aiConsent:false,aiResult:null,aiReviewed:false,clarification:'',
  profileAiConsent:state?.ai_personalization?.profile===true&&state?.ai_personalization?.health===true&&(m.sex!=='female'||state?.ai_personalization?.cycle===true),
  healthAiStored:state?.ai_personalization?.health===true,
  areas:Array.isArray(health.affected)?health.affected:[],
  pain:health.pain_score??0,course:health.symptom_course||'none',
  danger:health.danger_signs===true,cleared:health.activity_cleared===true,
  adult:!!state?.agreed,terms:!!state?.agreed,privacy:!!state?.agreed,health:!!state?.agreed};
 onboardErrors={};
}
function onboardError(key){
 return onboardErrors[key]?'<p class="fq-form-error" role="alert">'+esc(onboardErrors[key])+'</p>':'';
}
function onboardChoice(key,label,options){
 return '<label class="field"><span>'+esc(label)+'</span><select data-onboard="'+key+'">'+
 options.map(([name,value])=>'<option value="'+esc(value)+'"'+(String(onboard[key])===String(value)?' selected':'')+'>'+esc(name)+'</option>').join('')+'</select>'+onboardError(key)+'</label>';
}
function onboardInput(key,label,min,max,step){
 return '<label class="field"><span>'+esc(label)+'</span><input data-onboard="'+key+'" type="number" inputmode="decimal" min="'+min+'" max="'+max+'" step="'+step+'" value="'+esc(onboard[key])+'">'+onboardError(key)+'</label>';
}
function onboardCheckbox(key,label){
 return '<label class="fq-onboard-check"><input type="checkbox" data-onboard="'+key+'"'+(onboard[key]?' checked':'')+'><span>'+label+'</span></label>'+onboardError(key);
}
function onboardButtons(key,label,options){
 return '<div class="fq-onboard-choice"><h3 class="section-label">'+esc(label)+'</h3><div class="option-grid'+(key==='sex'?' fq-sex-options':key==='equipment'?' fq-equipment-options':'')+'">'+
 options.map(([name,val])=>'<button type="button" class="choice'+(String(onboard[key])===String(val)?' on':'')+
 '" data-onboard-pick="'+esc(key)+'" data-value="'+esc(val)+'" aria-pressed="'+(String(onboard[key])===String(val))+'">'+esc(name)+'</button>').join('')+'</div>'+onboardError(key)+'</div>';
}
function onboardWeekdays(){
 return '<div class="fq-onboard-choice"><h3 class="section-label" id="onboard-weekdays-label">Дни тренировок</h3>'+
  '<div class="fq-weekday-options" role="group" aria-labelledby="onboard-weekdays-label">'+
  weekdayNames.map((name,day)=>'<button type="button" class="choice'+(onboard.weekdays.includes(day)?' on':'')+
  '" data-onboard-weekday="'+day+'" aria-pressed="'+onboard.weekdays.includes(day)+'">'+name+'</button>').join('')+'</div>'+
  '<p class="input-note" aria-live="polite">Выбрано '+onboard.weekdays.length+' дн. в неделю. Количество тренировок определяется автоматически.</p>'+
  onboardError('weekdays')+'</div>';
}
function onboardForm(){
 initOnboard();
 const d=onboard;
 const intro='<p class="intro">Одна анкета. Все значения сохраняются без удаления истории.</p>';
 const personal='<h2 class="section-label" style="margin-top:0">Основные параметры</h2>'+
  onboardButtons('sex','Пол',[['Мужской','male'],['Женский','female']])+
  '<div class="form-row">'+onboardInput('age','Возраст',18,100,1)+onboardInput('height_cm','Рост, см',100,240,.1)+
  onboardInput('weight_kg','Вес, кг',25,300,.1)+'</div>'+
 '<label class="field"><span>Часовой пояс *</span><input data-onboard="timezone" type="search" list="fq-timezones" required autocomplete="off" value="'+esc(d.timezone)+'" placeholder="Город / регион"></label>'+
 '<datalist id="fq-timezones">'+allTimezones().map(z=>'<option value="'+esc(z)+'"></option>').join('')+'</datalist>'+
 onboardError('timezone')+'<p class="input-note">Определён по устройству: '+esc(deviceZone())+'. Можно изменить; VPN не учитывается.</p>'+
 onboardCheckbox('timezoneConfirmed','Подтверждаю выбранный часовой пояс')+onboardCheckbox('adult','Мне исполнилось 18 лет');
 const training='<h2 class="section-label">Тренировки</h2>'+
  onboardButtons('goal','Цель',onboardChoices.goal)+onboardChoice('level','Опыт',onboardChoices.level)+
  onboardWeekdays()+onboardChoice('minutes','Продолжительность тренировки',onboardChoices.minutes)+
  onboardButtons('equipment','Место занятий',onboardChoices.equipment)+
  (d.equipment==='home'?'<label class="field"><span>Какой спортивный инвентарь у тебя есть дома?</span><textarea data-onboard="equipment_description" maxlength="400" rows="2" placeholder="Например: гантели, коврик, резинки. Если ничего нет — оставь поле пустым">'+esc(d.equipment_description)+'</textarea></label>':'');
 const health=block('<h2>Здоровье</h2>'+
  '<label class="field"><span>Есть ли заболевания, травмы или ограничения, которые нужно учитывать при тренировках?</span>'+
  '<textarea data-onboard="description" maxlength="800" rows="4" placeholder="Необязательно. Опиши своими словами.">'+esc(d.description)+'</textarea></label>'+
  '<p class="input-note">Описание необязательно. Без разбора ограничений ИИ приложение не делает медицинских выводов. При симптомах или травмах уточни безопасную нагрузку со специалистом.</p>'+
  onboardCheckbox('healthStorageConsent','Разрешаю сохранить описание здоровья в приватном дневнике (если оно указано)')+
  (String(d.description).trim()?''+
    (d.profileAiConsent&&state?.ai_personalization?.health?button('Разобрать описание','onboard-ai'): '')+
    (d.aiResult?'<div class="fq-live-banner" role="status"><strong>Проверь результат ИИ перед сохранением.</strong> '+esc(d.aiResult.short_summary||'')+'</div>'+
       (d.aiResult.needs_clarification&&d.aiResult.clarification_question?'<label class="field"><span>'+
        esc(d.aiResult.clarification_question)+'</span><textarea data-onboard="clarification" rows="2" maxlength="220" placeholder="Ответ необязателен"></textarea></label>'+
        button('Уточнить с ИИ (необязательно)','onboard-ai-clarify'):'')+
       onboardCheckbox('aiReviewed','Подтверждаю проверенные результаты анализа'):''):'')+
  onboardError('description'));
 const legal=block('<h2>Подтверждения</h2>'+
  onboardCheckbox('profileAiConsent','Разрешаю использовать Yandex AI для персонализации тренировок и питания с учётом предоставленных мной данных, включая описание ограничений здоровья и, для женского профиля, сведения менструального цикла')+
  '<p class="input-note"><a href="/mini/yandex-privacy" target="_blank" rel="noopener noreferrer">Конфиденциальность Yandex AI</a>. Согласие добровольное, его можно отозвать здесь.</p>'+
  onboardCheckbox('terms','Принимаю <a href="/mini/terms" target="_blank" rel="noopener noreferrer">условия использования</a>')+
  onboardCheckbox('privacy','Ознакомился с <a href="/mini/privacy" target="_blank" rel="noopener noreferrer">политикой конфиденциальности</a>')+
  onboardCheckbox('health','Понимаю, что FORMIQ не ставит диагнозы и не заменяет врача')+
  '<div class="fq-onboard-actions">'+(profileNotice?'<p role="status" class="input-note">'+esc(profileNotice)+'</p>':'')+button(ready()?'Сохранить изменения':'Сохранить анкету','onboard-save',true)+'</div>');
 const calendar=d.sex==='female'?(state?.metrics?.sex==='female'?femaleCalendar():block('<h2>Женский календарь</h2><p>Сохрани выбранный пол, чтобы открыть календарь.</p>')):'';
 const connections=view==='profile'?block('<h2>Подключения</h2><p class="input-note">Garmin Connect и FatSecret: синхронизация недоступна, подключения нет.</p>'):'';
 return h()+'<h1 class="title">'+(view==='profile'?'Профиль:':'Твой профиль')+'</h1>'+
  (view==='profile'?'':intro)+block(personal+training)+health+calendar+connections+legal;
}
function onboardingPayload(){
 const d=onboard,m=state?.metrics||{},errs={};
 if(!['male','female'].includes(d.sex))errs.sex='Выбери Мужской или Женский.';
 if(!Array.isArray(d.weekdays)||d.weekdays.length<1)errs.weekdays='Выбери хотя бы один день недели.';
 if(!d.adult)errs.adult='Подтверди возраст 18+.';
 if(!d.timezoneConfirmed)errs.timezoneConfirmed='Подтверди часовой пояс.';
 try{new Intl.DateTimeFormat('ru-RU',{timeZone:d.timezone})}catch(_e){errs.timezone='Введи корректный IANA-часовой пояс.'}
 for(const key of ['terms','privacy','health'])if(!d[key])errs[key]='Подтверди согласие.';
 const mm={};
 for(const [key,min,max,whole] of [['age',18,100,true],['height_cm',100,240,false],['weight_kg',25,300,false]]){
  const raw=String(d[key]??'').trim(),value=Number(raw.replace(',','.'));
  if(!raw||!Number.isFinite(value)||value<min||value>max||(whole&&!Number.isInteger(value)))errs[key]='Введи корректное значение: '+min+'–'+max+'.';
  else mm[key]=value;
 }
 const description=String(d.description||'').trim();
 if(description&&!d.healthStorageConsent)errs.healthStorageConsent='Для сохранения описания нужно отдельное согласие.';
 if(description&&d.aiResult&&!d.aiReviewed)errs.description='Проверь и подтверди результат ИИ.';
 if(!onboardChoices.minutes.some(x=>x[1]===String(d.minutes)))errs.minutes='Выбери длительность 20–120 минут.';
 onboardErrors=errs;
 if(Object.keys(errs).length){const first=Object.values(errs)[0];throw Error(first)}
 const count=d.weekdays.length;
 const prior=state?.health_profile||{};
 const reviewed=!!(d.aiResult&&d.aiReviewed);
 // A new unreviewed note is conservatively classified as "other" until a
 // professional or a separately authorized + confirmed AI analysis is available.
 const previousAreas=Array.isArray(prior.affected)?prior.affected:[];
 const noteChanged=!!description&&description!==(state?.health_description||'');
 const affected=reviewed?d.areas:
  (noteChanged?[...new Set([...previousAreas,'other'])]:previousAreas);
 const course=reviewed?(affected.length?(d.course||'unspecified'):'none'):
  (affected.includes('other')?'unspecified':prior.symptom_course||'none');
 const timezone=d.timezone;
 return {answers:{goal:d.goal,level:d.level,days:String(count),weekdays:[...d.weekdays].sort((a,b)=>a-b),
  equipment:d.equipment,age_group:'adult',minutes:d.minutes},
  metrics:{...mm,sex:d.sex},timezone,timezone_confirmed:true,
  health_description:description,health_storage_consent:!!d.healthStorageConsent,
  ai_profile_consent:!!d.profileAiConsent,ai_health_consent:!!d.profileAiConsent,ai_cycle_consent:!!(d.profileAiConsent&&d.sex==='female'),
  unified_ai_consent:!!d.profileAiConsent,
  health_profile:{affected,pain_score:reviewed?Number(d.pain||0):Number(prior.pain_score||0),
   symptom_course:course,danger_signs:reviewed?d.danger:prior.danger_signs===true,
   activity_cleared:reviewed?d.cleared:prior.activity_cleared===true},
  equipment_description:d.equipment==='home'?String(d.equipment_description).trim():'',
  terms:true,privacy:true,health:true};
}

async function loadFemalePeriods(){
 if(state?.metrics?.sex!=='female')return;
 periodBusy=true;
 try{
  const res=await request('period_list');
  periodEntries=Array.isArray(res.periods)?res.periods:[];
  periodPrediction=res.next_period||null;periodError='';
  if(!periodMonth&&periodEntries.length)periodMonth=periodEntries[0].start.slice(0,7);
 }catch(_e){periodError='Не удалось загрузить приватный календарь.'}
 finally{periodBusy=false;draw()}
}
function femaleCalendar(){
 if(state?.metrics?.sex!=='female'||onboard?.sex==='male')return '';
 const format=s=>{const [y,m,d]=String(s||'').split('-');return y&&m&&d?d+'.'+m+'.'+y:'—'};
 const months=[...new Set((periodEntries||[]).map(p=>p.start.slice(0,7)))];
 const current=months.includes(periodMonth)?periodMonth:months[0]||'';
 const selector=months.length?'<label class="field" style="margin-top:16px"><span>Месяц истории</span><select id="period-month">'+
  months.map(v=>'<option value="'+esc(v)+'"'+(v===current?' selected':'')+'>'+esc(v.slice(5,7)+'.'+v.slice(0,4))+'</option>').join('')+
  '</select></label>':'';
 const entries=(periodEntries||[]).filter(p=>p.start.slice(0,7)===current).map(p=>
  '<div class="fq-period-row"><span>'+format(p.start)+' — '+format(p.end)+'</span>'+
  button('Изменить','period-edit',false,'data-period-id="'+p.id+'"')+'</div>').join('');
 const estimate=periodPrediction?'<p class="input-note" role="status">Следующее начало, ориентировочно: <strong>'+
  esc(format(periodPrediction.date))+'</strong>. Это оценка по истории, не медицинский прогноз.</p>':
  '<p class="input-note">Примерная дата появится при трёх недавних записях с достаточно устойчивым интервалом.</p>';
 return '<section class="surface"><h2 class="section-label" style="margin-top:0">Женский календарь</h2>'+
  '<p class="input-note">Необязательный приватный дневник. Без отдельного согласия данные не отправляются в Yandex AI.</p>'+
  '<p class="input-note">Для передачи данных цикла в Yandex AI действует единое согласие анкеты. Отзыв не удаляет записи.</p>'+
  '<div class="fq-live-grid" style="margin-top:15px">'+
  '<label class="field"><span>Начало</span><input id="period-start" type="date" value="'+esc(periodDraft.start)+'"></label>'+
  '<label class="field"><span>Окончание</span><input id="period-end" type="date" value="'+esc(periodDraft.end)+'"></label></div>'+
  (periodError?'<p role="alert" class="fq-form-error">'+esc(periodError)+'</p>':'')+
  '<div class="workout-cta">'+button(periodEditing?'Сохранить исправление':'Добавить период','period-save',true)+
  (periodEditing?button('Отмена','period-cancel'):'')+'</div>'+
  '<h3 class="section-label">История по месяцам</h3>'+selector+(periodBusy?'<p>Загрузка...</p>':entries||'<p class="empty">Записей пока нет.</p>')+
  estimate+'</section>';
}

async function onboardChanged(e){
 const target=e.target;
 if(target?.id==='period-ai-consent'){
  const wanted=target.checked===true;
  try{
   const result=await request('ai_personalization_set',{field:'cycle',enabled:wanted});
   state.ai_personalization=result.consents;aiTrainingTip='';
  }catch(ex){periodError=ex.message||'Не удалось сохранить согласие'}
  draw();return;
 }
 if(!onboard||!target)return;
 const field=target.dataset?.onboard;
 if(!field)return;
 onboard[field]=target.type==='checkbox'?target.checked:target.value;
 delete onboardErrors[field];
 if(field==='description'){
  onboard.aiResult=null;onboard.aiReviewed=false;onboard.clarification='';
  // Show optional consent controls after the user finishes editing free text.
  if(e.type==='change')draw();
 }
 if(field==='aiConsent'&&!target.checked){onboard.aiResult=null;onboard.aiReviewed=false}
 if(field==='equipment'||field==='profileAiConsent')draw();
}

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
 if(restSkippedKey!==key)restSkippedKey='';
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
 const done=Number(w.done||0),total=Number(w.total||0);
 const summary='<span class="kicker">Силовая тренировка</span><h1 class="title">'+esc(w.title||'Тренировка')+'</h1>'+
  '<p class="intro workout-intro">Выполнено '+done+' из '+total+' подходов · результат хранится в дневнике.</p>';
 let content='';
 if(!c){
  content='<section class="surface workout-entry"><span class="eyebrow">ТРЕНИРОВКА ЗАВЕРШЕНА</span>'+
    '<h2 class="workout-exercise" style="font-size:25px">Все подходы обработаны</h2>'+
    '<p class="input-note">Сохрани результаты в истории тренировок.</p>'+
    button('Завершить тренировку','finish-confirm',true)+'</section>';
 }else if(restUntil>Date.now()&&restFor===nextKey()){
  const seconds=Math.ceil((restUntil-Date.now())/1000);
  content='<section class="surface rest-panel"><span class="eyebrow">ОТДЫХ ПО ПРОГРАММЕ · '+
   esc(c.rest_seconds||0)+' сек</span><div id="rest-count" class="rest-number" role="timer" aria-live="off">'+
   String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0')+
   '</div><p class="subtitle">Следующий подход: '+esc(c.name)+'</p>'+
   button('Пропустить отдых','rest-skip')+'</section>';
 }else{
  const target=c.low===c.high?String(c.low):String(c.low)+'–'+String(c.high);
  const unit=c.unit==='reps'?'повторений':c.unit==='sec'?'секунд':'минут';
  content='<section class="surface workout-entry" id="workout-entry"><span class="eyebrow">УПРАЖНЕНИЕ '+esc(c.index||1)+' ИЗ '+esc(w.exercise_count||1)+'</span>'+
   '<h2 class="workout-exercise">'+esc(c.name)+'</h2>'+
   '<p class="subtitle">Подход '+esc(c.set_no)+' из '+esc(c.set_count)+' · цель '+esc(target)+' '+unit+'</p>'+
   (c.previous?'<p class="input-note" style="margin-top:12px">Прошлый результат: '+esc(c.previous)+'</p>':'')+
   (c.tip?'<p class="input-note" style="margin-top:8px">'+esc(c.tip)+'</p>':'')+
   '<div class="workout-input-grid">'+
   (c.unit==='reps'?input('Вес, кг','weight','number','min="0" max="500" step="0.1" inputmode="decimal"'):
     '<div class="metric"><span>Выполняй упражнение по плану</span></div>')+
   input(c.unit==='reps'?'Повторений':'Время','reps','number','min="1" max="300" inputmode="numeric"')+
   '</div><p class="input-note" style="margin:13px 0 0">Отдых после подхода: '+esc(c.rest_seconds||0)+' сек. При боли прекрати упражнение.</p>'+
   '<div class="workout-cta">'+button('Подход выполнен','record',true)+'</div></section>';
 }
 const exercises=Array.isArray(w.exercises)?w.exercises:[];
 const overview=exercises.length?'<section class="surface soft workout-plan-list">'+
  '<h2 style="font-size:17px;margin:0 0 10px">План упражнений</h2>'+
  exercises.map(e=>'<div class="workout-plan-row '+(c&&Number(c.position)===Number(e.position)?'current':'')+'">'+
   '<span>'+esc(e.name)+'</span><strong>'+esc(e.done)+' / '+esc(e.total)+'</strong></div>').join('')+
  '</section>':'';
 const footer=c?'<div class="fq-live-actions workout-secondary-actions" role="group" aria-label="Управление тренировкой" style="margin-top:14px">'+
  button('Пропустить упражнение','skip-confirm')+button('Завершить','finish-confirm')+'</div>':'';
 return h()+summary+content+footer+overview;
}
function training(){
 if(!ready()){onboardOpen=true;return onboardForm()}
 if(active())return workout();
 const nextDay=String(state.next_day||''),ix='ABCDEFG'.indexOf(nextDay);
 const items=ix>=0&&Array.isArray(state.plan?.[ix])?state.plan[ix]:[];
 const next=(state.calendar||[]).find(row=>row.status==='planned'&&row.day===nextDay);
 const title=state.plan_names?.[ix]||next?.title||'Тренировка';
 const timeZone=state?.metrics?.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone;
 let dayLabel='';
 try{dayLabel=new Intl.DateTimeFormat('ru-RU',{weekday:'long',day:'numeric',month:'long',timeZone}).format(new Date())}
 catch(_e){dayLabel=new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long'}).format(new Date())}
 const exercises=items.map(e=>'<div class="exercise"><span class="exercise-name">'+esc(e.name)+
  '</span><span class="exercise-reps">'+esc(e.sets)+' × '+esc(e.low)+(e.high!==e.low?'–'+esc(e.high):'')+'</span></div>').join('');
 const trainingCard='<section class="surface"><div class="heading-row"><span class="eyebrow">БЛИЖАЙШАЯ ТРЕНИРОВКА</span></div>'+
  '<div class="heading-row"><h2>'+esc(title)+'</h2></div>'+
  '<p class="subtitle">'+esc(next?.date_ru||'Дата уточняется по плану')+'</p><div class="divider"></div>'+
  (exercises||'<p class="empty">План упражнений пока не сформирован.</p>')+
  (items.length?'<div class="workout-cta">'+button('Начать тренировку','mood',true)+'</div>':'')+
  '</section>';
 const selected=cardioType||'Выбрать вид кардио';
 const cardioCard='<section class="surface cardio-inline" id="cardio-entry">'+
  '<div class="heading-row"><h2 style="margin:0;font-size:21px">Дополнительная тренировка</h2></div>'+
  '<p class="input-note" style="margin:9px 0 15px">Активность вне основного тренировочного плана.</p>'+
  '<div class="field"><span>Вид кардио</span>'+
  button(selected,'cardio-types',false,'aria-expanded="'+typesOpen+'" aria-controls="cardio-type-options"')+
  '</div>'+
  (typesOpen?'<div class="cardio-choices cardio-inline-choices" id="cardio-type-options">'+
   ['Ходьба','Бег','Велосипед','Плавание','Другое'].map(type=>
     button(type,'cardio-type',false,'data-type="'+esc(type)+'" aria-pressed="'+(cardioType===type)+'"')).join('')+
   '</div>':'')+
  (cardioType==='Другое'?'<label class="field"><span>Название активности</span><textarea id="cardio-activity" rows="2" maxlength="100" placeholder="Играл в теннис, работал в саду...">'+esc(drafts['cardio-activity']||'')+'</textarea></label>'+
  '<label class="field"><span>Предполагаемая интенсивность</span><select id="cardio-intensity">'+
  [['light','Лёгкая'],['moderate','Средняя'],['vigorous','Высокая']].map(([v,label])=>'<option value="'+v+'"'+((drafts['cardio-intensity']||'moderate')===v?' selected':'')+'>'+label+'</option>').join('')+'</select></label>':'')+
  '<div class="cardio-input-grid">'+
    input('Время, мин','cardio-min','number','min="1" max="300" inputmode="numeric" placeholder="60"')+
    '<label class="field"><span>Средний пульс <small>необязательно</small></span>'+
    '<input id="cardio-hr" type="number" min="40" max="220" inputmode="numeric" autocomplete="off" placeholder="—" value="'+esc(drafts['cardio-hr']??'')+'"></label>'+
  '</div><div style="margin-top:15px">'+button('Сохранить тренировку','cardio',true)+'</div>'+
  '<p class="input-note" style="margin-top:11px">Сохранено в дневнике. Оценка ккал по MET приблизительная, не измеренная датчиком.</p></section>';
 const clock=localClock(),greeting=clock.hour<11?'Доброе утро!':clock.hour<17?'Добрый день!':clock.hour<23?'Добрый вечер!':'Доброй ночи!';
 const dayWorkout=(state.calendar||[]).some(r=>r.date===clock.date&&r.status!=='done'&&r.status!=='retired');
 const message=dayWorkout?'Сегодня всё по твоему плану.':'Сегодня день восстановления.';
 return h()+'<span class="kicker fq-home-date">'+esc(dayLabel)+'</span><h1 class="title">'+esc(greeting)+'</h1>'+
  '<p class="intro">'+esc(message)+'</p><section class="surface soft">'+button('Отзывы и предложения','feedback-open')+
  (feedbackNotice?'<p role="status" class="input-note">'+esc(feedbackNotice)+'</p>':'')+'</section>'+trainingCard+cardioCard;
}
const isoDate=ru=>{const p=String(ru||'').split('.');return p.length===3?`${p[2]}-${p[1]}-${p[0]}`:''};
const prettyDate=iso=>{const p=String(iso||'').split('-');return p.length===3?`${p[2]}.${p[1]}.${p[0]}`:iso};
function currentMonth(){
 const today=new Date();
 try{
  const parts=new Intl.DateTimeFormat('en',{timeZone:state?.metrics?.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone,year:'numeric',month:'2-digit'}).formatToParts(today);
  return parts.find(p=>p.type==='year').value+'-'+parts.find(p=>p.type==='month').value;
 }catch(_e){return today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')}
}
const filtered=()=>date?(dayRows??(state?.history||[]).filter(x=>isoDate(x.date)===date)):(state?.history||[]);
const historyRow=x=>'<button type="button" class="cardio-history-row fq-history-action" data-cmd="detail" data-id="'+esc(x.id)+'">'+
 '<span><strong>'+esc(x.title)+'</strong><small>'+esc(x.date)+'</small></span>'+
 '<span class="plan-chevron" aria-hidden="true">›</span></button>';
function calendar(){
 if(!month)month=currentMonth();
 const [year,n]=month.split('-').map(Number);
 const first=new Date(Date.UTC(year,n-1,1)),count=new Date(Date.UTC(year,n,0)).getUTCDate();
 const padding=(first.getUTCDay()+6)%7;
 const highlighted=new Set([...monthMarks,...(state.history||[]).map(x=>isoDate(x.date))]);
 return '<div class="history-cal-inline" id="history-calendar-grid" aria-label="Календарь тренировок">'+
   '<div class="calendar-controls">'+
   '<button type="button" data-cmd="prev-month" aria-label="Предыдущий месяц">‹</button>'+
   '<strong>'+esc(first.toLocaleDateString('ru-RU',{month:'long',year:'numeric',timeZone:'UTC'}))+'</strong>'+
   '<button type="button" data-cmd="next-month" aria-label="Следующий месяц">›</button></div>'+
   '<div class="history-cal-grid">'+
   ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(x=>'<span class="cal-weekday">'+x+'</span>').join('')+
   '<span aria-hidden="true"></span>'.repeat(padding)+
   Array.from({length:count},(_,i)=>{
     const day=month+'-'+String(i+1).padStart(2,'0');
     return '<button type="button" class="'+(highlighted.has(day)?'has-entry has-workout ':'')+
       (date===day?'selected':'')+'" data-date="'+day+'" aria-label="'+prettyDate(day)+'">'+(i+1)+'</button>'
   }).join('')+'</div>'+
   '<p class="cal-help"><span class="history-legend-dot"></span> Отмечены дни с записями в дневнике.</p></div>';
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
 return '<section class="surface" id="history-root">'+
 '<div class="heading-row"><h2 style="margin:0;font-size:20px">История тренировок</h2>'+
 button('По датам','calendar',false,'aria-expanded="'+calendarOpen+'" aria-controls="history-calendar-grid"')+
 '</div>'+(calendarOpen?calendar():'')+
 (date?'<div class="date-filter-summary"><strong>Дата: '+prettyDate(date)+'</strong>'+
 button('Сбросить','reset-date')+'</div>':'')+
 '<div class="cardio-history">'+(filtered().slice(0,3).map(historyRow).join('')||
 '<p class="empty">За эту дату записей нет.</p>')+'</div>'+
 '<div style="margin-top:13px">'+button('Вся история →','history-all')+'</div></section>';
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

function periodShortLabel(i){
 const start=state?.cycle_start;
 if(!start||!/^\d{4}-\d{2}-\d{2}$/.test(start))return 'Период '+i;
 const base=new Date(start+'T12:00:00Z');
 if(Number.isNaN(base.getTime()))return 'Период '+i;
 const a=new Date(base.getTime()+(i-1)*7*86400000),b=new Date(a.getTime()+6*86400000);
 const month=d=>new Intl.DateTimeFormat('ru-RU',{month:'long',timeZone:'UTC'}).format(d);
 return a.getUTCFullYear()===b.getUTCFullYear()&&a.getUTCMonth()===b.getUTCMonth()
  ?a.getUTCDate()+'–'+b.getUTCDate()+' '+month(a)
  :a.getUTCDate()+' '+month(a)+' — '+b.getUTCDate()+' '+month(b);
}

function trainingPlanCard(){
 // Reuse the actual PostgreSQL-backed cycle calendar and original week details;
 // this is not a second schedule, nor a newly generated four-week cycle.
 if(!state?.cycle_start||!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(state.cycle_start)){
  return '<section class="surface" id="training-plan"><h2 style="font-size:20px;margin:0 0 14px">Тренировочный план</h2>'+
   '<p class="empty">План появится после формирования тренировочного цикла.</p></section>';
 }
 const rows=state?.calendar||[];
 const periods=[1,2,3,4].map(i=>{
  const dates=rows.filter(r=>r.week===i);
  const toggle='<button type="button" class="'+(week===i?'on':'')+'" data-cmd="week" data-week="'+i+'" aria-label="'+esc(periodLabel(i))+'" aria-expanded="'+(week===i)+'">'+
   '<span><span class="week-range">'+esc(periodShortLabel(i))+'</span><small class="week-meta">'+
   dates.length+' занятий по сохранённому расписанию</small></span><span class="week-chevron" aria-hidden="true">'+(week===i?'⌄':'›')+'</span></button>';
  const entries=dates.map(r=>'<div class="plan-entry"><span><strong>'+esc(r.title)+'</strong><small>'+
    esc(r.date_ru||prettyDate(r.date))+' · '+(r.status==='done'?'Выполнено':r.status==='planned'?'Запланировано':'По расписанию')+
    '</small></span><span class="plan-chevron" aria-hidden="true">›</span></div>').join('');
  return '<div class="week-group">'+toggle+(week===i?'<div class="week-details"><div class="plan-list">'+
   (entries||'<p class="empty">На этот период занятий нет.</p>')+'</div></div>':'')+'</div>';
 }).join('');
 return '<section class="surface" id="training-plan" aria-label="Тренировочный план">'+
  '<h2 style="font-size:20px;margin:0 0 14px">Тренировочный план</h2>'+
  '<div class="week-selector fq-plan-period-grid" role="group" aria-label="Четыре недели тренировок">'+periods+'</div>'+
  '</section>';
}
function weightChart(points,exerciseName){
 const data=(Array.isArray(points)?points:[]).filter(p=>
  /^\d{4}-\d{2}-\d{2}$/.test(String(p.date))&&Number.isFinite(Number(p.weight))&&
  Number(p.weight)>0&&Number(p.weight)<=500).slice(-8);
 if(!data.length)return '<div class="fq-empty-chart">Для этого упражнения пока нет записанного веса.</div>';
 const values=data.map(p=>Number(p.weight));
 const lower=Math.min(...values),upper=Math.max(...values);
 // Use a regular whole-kilogram tick grid, not decimal quarter ticks.
 const tickStep=Math.max(5,5*Math.ceil((upper-lower+2)/15));
 const yMin=Math.max(0,Math.floor((lower-1)/tickStep)*tickStep);
 const yMax=yMin+4*tickStep;
 const w=340,h=177,left=44,right=12,top=16,bottom=39;
 const x=i=>left+(data.length===1?(w-left-right)/2:i*(w-left-right)/(data.length-1));
 const y=v=>top+(yMax-v)/(yMax-yMin)*(h-top-bottom);
 const format=v=>v.toLocaleString('ru-RU',{maximumFractionDigits:2});
 const guides=Array.from({length:5},(_,i)=>{
  const mass=yMin+(yMax-yMin)*i/4,yy=y(mass);
  return '<line x1="'+left+'" y1="'+yy+'" x2="'+(w-right)+'" y2="'+yy+
   '" stroke="#b3c0bc" stroke-opacity=".62"/>'+
   '<text x="'+(left-8)+'" y="'+(yy+4)+'" fill="#556568" font-size="10" text-anchor="end">'+format(mass)+'</text>';
 }).join('');
 const path=data.length>1?'<polyline points="'+data.map((p,i)=>x(i)+','+y(values[i])).join(' ')+
  '" fill="none" stroke="#526762" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>':'';
 const marks=data.map((p,i)=>'<circle cx="'+x(i)+'" cy="'+y(values[i])+
  '" r="4" fill="#526762" stroke="#f1f5f2" stroke-width="2"/>'+
  '<text x="'+x(i)+'" y="'+(h-12)+'" text-anchor="middle" font-size="10" fill="#556467">'+
  esc(p.date.slice(8,10)+'.'+p.date.slice(5,7))+'</text>').join('');
 return '<svg class="chart-area fq-progress-chart" viewBox="0 0 '+w+' '+h+
  '" role="img" aria-label="'+esc(exerciseName+' — '+data.map(p=>p.date+' '+format(Number(p.weight))+' кг').join('; '))+'">'+
  '<text x="6" y="10" font-size="10" fill="#556568">кг</text>'+guides+path+marks+'</svg>';
}
async function loadProgressSeries(){
 if(!ready()||progressLoading)return;
 progressLoading=true;progressError='';
 if(view==='progress'&&!onboardOpen)draw();
 try{
  const response=await request('progress_series');
  progressSeries=Array.isArray(response.exercises)?response.exercises:[];
 }catch(_error){
  progressSeries=null;
  progressError='Не удалось загрузить график. Открой «Прогресс» ещё раз.';
 }finally{
  progressLoading=false;
  if(view==='progress'&&!onboardOpen)draw();
 }
}
function progress(){
 const stats=state.stats||{},weight=state.metrics?.weight_kg;
 const valid=weight!==null&&weight!==undefined&&Number.isFinite(Number(weight))&&Number(weight)>0;
 const shown=valid?esc(Number(weight).toLocaleString('ru-RU',{maximumFractionDigits:2}))+' кг':'—';
 const exercises=Array.isArray(progressSeries)?progressSeries:[];
 const selected=exercises.find(e=>e.key===progressSelected)||exercises[0]||null;
 const choices=selected?'<div class="segmented fq-progress-exercises" style="grid-template-columns:repeat('+
  Math.min(4,exercises.length)+',minmax(0,1fr))">'+exercises.map(e=>
   '<button type="button" class="'+(e.key===selected.key?'on':'')+'" data-cmd="progress-exercise" data-key="'+
   esc(e.key)+'" aria-pressed="'+(e.key===selected.key)+'">'+esc(e.name)+'</button>').join('')+'</div>':'';
 const chart=progressLoading?'<div class="chart-block fq-empty-chart" role="status">Загружаем сохранённые результаты…</div>':
  progressError?'<div class="chart-block fq-empty-chart" role="alert">'+esc(progressError)+'</div>':
  selected?choices+'<div class="chart-block">'+weightChart(selected.points,selected.name)+'</div>'+
   '<p class="chart-leg">Максимальный сохранённый вес по каждому дню. Только завершённые тренировки.</p>':
  '<div class="chart-block fq-empty-chart" role="status">Пока нет завершённых подходов с записанным весом.</div>';
 const strength='<section class="surface"><div class="chart-caption"><strong>Рабочий вес</strong><small>По записям подходов</small></div>'+chart+'</section>';
 const body='<section class="surface"><div class="chart-caption"><strong>Масса тела</strong><small>Последнее измерение</small></div>'+
  '<div class="metric"><span>Вес в профиле</span><strong>'+shown+'</strong><span>'+
  (valid?'Последнее сохранённое значение · динамика пока недоступна':'Нет измерений')+'</span></div></section>';
 const summary='<section class="surface"><h2 style="font-size:20px;margin:0 0 14px">Результаты</h2>'+
  '<div class="summary-grid"><div class="metric"><span>Тренировок</span><strong>'+esc(stats.total??0)+'</strong></div>'+
  '<div class="metric"><span>Выполненных подходов</span><strong>'+esc(stats.sets??0)+'</strong></div></div></section>';
 return h()+'<span class="kicker">История и результаты</span><h1 class="title">Прогресс</h1>'+
  '<p class="intro">Результаты из сохранённого дневника.</p>'+strength+body+summary+trainingPlanCard()+history();
}
function food(){
 const today='<section class="surface"><span class="eyebrow">СЕГОДНЯ · ПИТАНИЕ</span>'+
  '<div class="nutrition-today" style="margin-top:15px"><div class="nutrition-ring"><b>—</b><span>ккал</span></div>'+
  '<div><h3>Нет данных</h3><p>Автоматический дневник пока не подключён. Калории и норму не придумываем.</p></div></div></section>';
 const macros='<section class="surface"><h2 style="font-size:21px;margin:0 0 18px">Белки, жиры, углеводы</h2>'+
  ['Белки','Жиры','Углеводы'].map(label=>'<div class="macro"><strong>'+label+'</strong><span>— г · нет данных</span></div>').join('')+'</section>';
 const meals='<section class="surface soft"><h2 style="font-size:20px;margin:0 0 10px">Приёмы пищи</h2>'+
  '<p class="empty">Записей пока нет. Автоматический дневник не подключён.</p></section>';
 const report='<section class="surface"><h2 style="font-size:21px;margin:0 0 10px">Анализ отчёта</h2>'+
  '<p class="input-note" style="margin:0 0 17px">Выбери настоящий CSV или изображение отчёта. Покажем только то, что есть в отчёте.</p>'+
  '<label class="field"><span>Отчёт питания</span><input id="nutrition-file" type="file" accept=".jpg,.jpeg,.png,.csv,image/jpeg,image/png,text/csv"></label>'+
  '<label class="checkbox-line" style="margin-top:15px"><input id="nutrition-consent" type="checkbox">'+
  '<span>Разрешаю отправить отчёт в Yandex AI для анализа. Исходный файл не сохраняется в дневнике.</span></label>'+
  '<p class="input-note" style="margin:11px 0">Отдельное согласие на ИИ можно изменить в анкете.</p>'+
  '<p id="nutrition-error" class="fq-live-error" role="alert"></p>'+
  button(nutritionBusy?'Анализируем...':'Проанализировать','nutrition-analyze',true,nutritionBusy?'disabled':'')+
  (nutritionAnswer?'<p role="status" class="fq-live-banner" style="white-space:pre-wrap;margin-top:14px">'+esc(nutritionAnswer)+'</p>':'')+'</section>';
 return h()+'<span class="kicker">Рацион</span><h1 class="title">Питание</h1>'+
  '<p class="intro">Понятный дневник без выдуманных показателей.</p>'+today+macros+meals+report;
}
function profile(){return onboardForm();}
function modalHTML(){
 if(!modal)return '';
 let content='';
 if(modal==='feedback')content='<h2>Отзывы и предложения</h2>'+(feedbackError?'<p role="alert" class="fq-form-error">'+esc(feedbackError)+'</p>':'')+
  '<label class="field"><span>Отзыв, ошибка или идея</span><textarea id="feedback-text" rows="5" maxlength="800" placeholder="8–800 символов">'+esc(drafts['feedback-text']||'')+'</textarea></label>'+
  button('Отправить','feedback-send',true)+button('Отмена','close');
 if(modal==='cardio'){
  content='<h2>Дополнительная тренировка</h2><p>Активность вне основного плана.</p>'+
   '<label class="field"><span>Вид активности</span>'+button(cardioType||'Выбрать вид активности','cardio-types')+'</label>'+
   (typesOpen?'<div class="fq-live-actions">'+['Ходьба','Бег','Велосипед','Плавание','Другое'].map(x=>button(x,'cardio-type',false,'data-type="'+esc(x)+'"')).join('')+'</div>':'')+
   (cardioType==='Другое'?'<label class="field"><span>Название активности</span><textarea id="cardio-activity" rows="2" maxlength="100" placeholder="Играл в теннис, работал в саду...">'+esc(drafts['cardio-activity']||'')+'</textarea></label>'+
     '<label class="field"><span>Предполагаемая интенсивность</span><select id="cardio-intensity">'+
      [['light','Лёгкая'],['moderate','Средняя'],['vigorous','Высокая']].map(([v,label])=>'<option value="'+v+'"'+((drafts['cardio-intensity']||'moderate')===v?' selected':'')+'>'+label+'</option>').join('')+'</select></label>':'')+
   '<div class="fq-live-grid" style="margin-top:15px">'+
    input('Время, мин','cardio-min','number','min="1" max="300" inputmode="numeric"')+
    input('Средний пульс','cardio-hr','number','min="40" max="220" inputmode="numeric"')+
   '</div><p class="input-note">Пульс необязателен. Калории по MET — приблизительная оценка.</p>'+
   button('Сохранить тренировку','cardio',true)+button('Отмена','close');
 }
 if(modal==='mood')content=state?.metrics?.sex==='female'?
  `<h2>Самочувствие перед началом</h2><p>Выбирай по реальному состоянию, не по фазе цикла.</p>${button('Хорошо — обычная тренировка','start-normal',true)}${button('Небольшой дискомфорт — облегчить','start-tired')}${button('Сильная боль или слабость — восстановление','start-severe')}${button('Совет ИИ при дискомфорте (если разрешён)','ai-tip-discomfort')}`:
  `<h2>Самочувствие перед началом</h2><p>Как себя чувствуешь?</p>${button('Хорошо','start-normal',true)}${button('Устал','start-tired')}`;
 if(modal==='finish')content=`<h2>Завершить тренировку?</h2><p>Оставшиеся подходы будут пропущены.</p>${button('Завершить','finish',true)}${button('Продолжить','close')}`;
 if(modal==='skip')content=`<h2>Пропустить упражнение?</h2>${button('Пропустить','skip',true)}${button('Продолжить','close')}`;
 if(modal==='history'){
  const rows=allRows.map(historyRow).join('');
  const body=rows||'<p class="empty">'+(nextOffset!==null?'Загружаем сохранённые занятия…':'В дневнике нет записей за выбранную дату.')+'</p>';
  content='<div class="history-top"><h2>История тренировок</h2>'+
   '<button type="button" class="history-close" data-cmd="close" aria-label="Закрыть историю">Закрыть</button></div>'+
   '<p class="input-note">'+(date?'Записи за '+prettyDate(date):'Силовые и кардио из твоего дневника')+'.</p>'+
   '<div class="history-scroll" role="region" aria-label="Список сохранённых занятий" tabindex="0">'+
     '<div class="cardio-history">'+body+'</div></div>'+
   (nextOffset!==null?button('Загрузить ещё','history-more'):'');
 }
 if(modal==='detail')content=`<div class="fq-live-topline"><h2>${esc(detail?.title)}</h2>${button('Закрыть','close')}</div><p>${esc(detail?.date)}</p>${(detail?.items||[]).map(x=>`<div class="fq-live-row"><span>${esc(x.name)}</span><strong>${esc(x.result)}</strong></div>`).join('')}`;
 return `<div class="fq-live-overlay"><div class="fq-live-dialog ${modal==='history'?'history-modal':''}" role="dialog" aria-modal="true" aria-label="${modal==='history'?'История тренировок':'Окно FORMIQ'}">${content}</div></div>`;
}
function draw(){
 document.body?.classList?.toggle('theme-female',((onboardOpen||view==='profile')&&onboard?onboard.sex:state?.metrics?.sex)==='female');
 document.body?.classList?.remove('cardio-typing','workout-typing');
 if(!token){app.innerHTML=`<main class="view">${page('FORMIQ',block('<h2>Открой из Telegram</h2><p>Для входа необходима авторизация Telegram.</p>'))}</main>`;return}
 if(!state){app.innerHTML=`<main class="view">${h()}${block(`<h2>${error?'Не удалось загрузить дневник':'Загружаем дневник...'}</h2>${error?`<p class="fq-live-error" role="alert">${esc(error)}</p><p>Перезапусти приложение через Telegram.</p>`:''}`)}</main>`;return}
 app.innerHTML=`<main class="view">${error?`<p class="fq-live-error" role="alert">${esc(error)}</p>`:''}${onboardOpen?onboardForm():view==='home'?training():view==='progress'?progress():view==='food'?food():profile()}</main>${ready()&&!onboardOpen?nav():''}${modalHTML()}`;
}
function partialHistory(){const el=document.getElementById('history-root');if(el)el.outerHTML=history();else draw()}
function fail(s){error=s;draw()}
app.addEventListener('input',e=>{
 onboardChanged(e);
 if(['reps','weight','cardio-min','cardio-hr','cardio-activity','cardio-intensity','feedback-text'].includes(e.target.id))drafts[e.target.id]=e.target.value;
 if(e.target.id==='period-start'||e.target.id==='period-end')periodDraft[e.target.id==='period-start'?'start':'end']=e.target.value;
 if(e.target.id==='period-month'){periodMonth=e.target.value;draw()}
 const metric=String(e.target.id||'').replace(/^profile-/,'');
 if(metricEdit&&profileDraft&&Object.prototype.hasOwnProperty.call(profileDraft,metric))profileDraft[metric]=e.target.value;
});
app.addEventListener('change',onboardChanged);
app.addEventListener('focusin',e=>{
 if(!['reps','weight','cardio-min','cardio-hr','profile-age','profile-height_cm','profile-weight_kg'].includes(e.target.id))return;
 if(['cardio-min','cardio-hr'].includes(e.target.id))document.body?.classList?.add('cardio-typing');
 const field=e.target,card=e.target.closest('.surface');
 if(!card)return;
 const shift=()=>{if(document.activeElement===field)updateViewportPosition()};
 shift();setTimeout(shift,130);setTimeout(shift,320);
});
app.addEventListener('focusout',e=>{
 if(['cardio-min','cardio-hr'].includes(e.target.id))document.body?.classList?.remove('cardio-typing');
});
window.visualViewport?.addEventListener('resize',updateViewportPosition);
window.visualViewport?.addEventListener('scroll',updateViewportPosition);
app.addEventListener('click',async e=>{
 const element=e.target.closest('button');if(!element||busy)return;
 if(element.dataset.nav){if(!ready()){onboardOpen=true;view='home';error='';draw();return}onboardOpen=false;onboard=null;view=element.dataset.nav;error='';draw();window.scrollTo(0,0);if(view==='progress')loadProgressSeries();if(view==='profile'){initOnboard();loadFemalePeriods()}return}
 if(element.dataset.date){date=element.dataset.date;dayRows=null;calendarOpen=false;partialHistory();await loadDay();return}
 const cmd=element.dataset.cmd;
 if(['ai-profile-revoke','ai-health-revoke','ai-cycle-revoke'].includes(cmd)){
  const field={'ai-profile-revoke':'profile','ai-health-revoke':'health','ai-cycle-revoke':'cycle'}[cmd];
  try{
   const result=await request('ai_personalization_set',{field,enabled:false});
   state.ai_personalization=result.consents;
   aiTrainingTip='';aiNutritionTip='';
   profileNotice='Согласие отозвано. История тренировок и календарь сохранены.';
  }catch(ex){profileNotice=ex.message||'Не удалось изменить согласие'}
  draw();return;
 }
 if(cmd==='ai-tip-training'||cmd==='ai-tip-nutrition'||cmd==='ai-tip-discomfort'){
  if(aiTipBusy)return;
  aiTipBusy=true;const purpose=cmd==='ai-tip-nutrition'?'nutrition':'training';
  try{
   const result=await request('ai_personalized_guidance',{
      purpose,mood:cmd==='ai-tip-discomfort'?'discomfort':'normal'});
   if(purpose==='training'){aiTrainingTip=result.advice;modal=''}
   else aiNutritionTip=result.advice;
  }catch(ex){error=ex.message||'Не удалось получить совет ИИ'}
  finally{aiTipBusy=false;draw()}
  return;
 }
 if(cmd==='period-edit'){
  const id=Number(element.dataset.periodId),record=periodEntries?.find(x=>x.id===id);
  if(!record)return;
  periodEditing=id;periodDraft={start:record.start,end:record.end};periodError='';draw();return;
 }
 if(cmd==='period-cancel'){
  periodEditing=null;periodDraft={start:'',end:''};periodError='';draw();return;
 }
 if(cmd==='period-save'){
  if(periodBusy)return;
  if(!periodDraft.start||!periodDraft.end){periodError='Укажи обе даты.';draw();return}
  if(periodDraft.end<periodDraft.start){periodError='Окончание не может быть раньше начала.';draw();return}
  periodBusy=true;
  try{
   const response=await request('period_save',{...periodDraft,...(periodEditing?{id:periodEditing}:{})});
   periodEntries=response.periods||[];periodPrediction=response.next_period||null;
   periodMonth=periodDraft.start.slice(0,7);
   periodEditing=null;periodDraft={start:'',end:''};periodError='';
  }catch(e){periodError=e.message||'Не удалось сохранить даты.'}
  finally{periodBusy=false;draw()}
  return;
 }
 if(element.dataset.onboardWeekday!==undefined){
  if(!(onboardOpen||view==='profile')||!onboard)return;
  const day=Number(element.dataset.onboardWeekday);
  if(!Number.isInteger(day)||day<0||day>6)return;
  onboard.weekdays=onboard.weekdays.includes(day)?onboard.weekdays.filter(d=>d!==day):[...onboard.weekdays,day].sort((a,b)=>a-b);delete onboardErrors.weekdays;
  draw();app.querySelector?.('[data-onboard-weekday="'+day+'"]')?.focus();return;
 }
 if(element.dataset.onboardPick){
  if(!(onboardOpen||view==='profile')||!onboard)return;
  const key=element.dataset.onboardPick,value=element.dataset.value;
  if(!['goal','equipment','sex'].includes(key))return;
  onboard[key]=value;delete onboardErrors[key];
  draw();return;
 }
 if(cmd==='progress-exercise'){if(progressSeries?.some(item=>item.key===element.dataset.key)){progressSelected=element.dataset.key;draw()}return}
   if(cmd==='onboard-open'){onboardOpen=true;initOnboard();error='';draw();window.scrollTo(0,0);return}
 if(cmd==='onboard-cancel'){onboardOpen=false;onboard=null;error='';draw();return}
 if(cmd==='onboard-ai'||cmd==='onboard-ai-clarify'){
  if(!onboard?.profileAiConsent||!state?.ai_personalization?.health){fail('Для разбора сначала сохрани единое согласие Yandex AI в анкете.');return}
  if(!onboard.adult||!onboard.privacy){fail('Перед анализом подтверди возраст 18+ и ознакомление с политикой конфиденциальности.');return}
  const original=String(onboard.description||'').trim();
  const extra=cmd==='onboard-ai-clarify'?String(onboard.clarification||'').trim():'';
  const txt=extra?original+'\nДополнительное пояснение пользователя: '+extra:original;
  if(txt.length<8||txt.length>800){fail('Опиши ограничения от 8 до 800 символов.');return}
  const analyzedForm=onboard;
  const result=await send('health_analyze',{adult:true,privacy_ack:true,ai_consent:true,text:txt});
  if(result?.analysis){
   if(onboard!==analyzedForm||String(onboard.description||'').trim()!==original||
      (cmd==='onboard-ai-clarify'&&String(onboard.clarification||'').trim()!==extra)||
      !onboard.profileAiConsent||!onboard.adult||!onboard.privacy){
    fail('Описание или согласия изменились во время анализа. Проверь их и запусти разбор заново.');return;
   }
   const a=result.analysis;onboard.limitation='yes';
   onboard.areas=Array.isArray(a.affected)?a.affected.filter(k=>onboardRegions.some(([id])=>id===k)):[];
   onboard.pain=Number.isInteger(a.pain_score)?String(a.pain_score):'0';
   onboard.course=['stable','recent','worsening'].includes(a.symptom_course)?a.symptom_course:'';
   onboard.danger=a.danger_signs===true;onboard.cleared=false;
   onboard.aiResult=a;onboard.aiReviewed=false;onboard.clarification='';draw();
  }return;
 }
 if(cmd==='onboard-save'){
  if(!onboard)return;let payload;
  try{payload=onboardingPayload()}catch(e){fail(e.message);return}
  const saved=await send('onboarding',payload);
  if(saved){const editing=view==='profile';onboardOpen=false;onboard=null;onboardErrors={};view=editing?'profile':'home';profileNotice=editing?'Изменения сохранены.':'';draw();window.scrollTo(0,0)}
  return;
 }
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
 if(cmd==='feedback-open'){feedbackError='';modal='feedback';draw();return}
 if(cmd==='feedback-send'){const msg=String(document.getElementById('feedback-text')?.value||drafts['feedback-text']||'').trim();
  if(msg.length<8||msg.length>800){feedbackError='Напиши от 8 до 800 символов.';draw();return}
  try{const result=await request('feedback',{text:msg});feedbackNotice=result.message||'Спасибо! Отзыв сохранён.';drafts['feedback-text']='';modal='';error='';draw()}
  catch(ex){feedbackError=ex.message||'Не удалось сохранить отзыв.';draw()}return;
 }
 if(cmd==='close'){modal='';draw();return}
 if(cmd==='cardio-add'){modal='cardio';typesOpen=false;draw();return}
 if(cmd==='mood'){modal='mood';draw();return}
 if(cmd==='start-severe'){
  modal='';error='Тренировка не начата. При сильной боли или слабости лучше восстановиться. При выраженных или усиливающихся симптомах обратись за медицинской помощью.';
  draw();return;
 }
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
 if(cmd==='finish'){modal='';const response=await send('finish');if(response){view='progress';restUntil=0;restFor='';storeRestTimer();if(date){dayRows=null;await loadDay()}progressSeries=null;loadProgressSeries()}draw();return}
 if(cmd==='skip'){modal='';await send('skip');return}
 if(cmd==='cardio-types'){typesOpen=!typesOpen;draw();return}
 if(cmd==='cardio-type'){cardioType=element.dataset.type||'';typesOpen=false;draw();return}
 if(cmd==='cardio'){
  if(!cardioType){fail('Сначала выбери вид кардио.');return}
  const m=document.getElementById('cardio-min')?.value.trim()||'',p=document.getElementById('cardio-hr')?.value.trim()||'';
  if(!/^\d+$/.test(m)||Number(m)<1||Number(m)>300){fail('Время кардио от 1 до 300 минут.');return}
  if(p&&(!/^\d+$/.test(p)||Number(p)<40||Number(p)>220)){fail('Средний пульс 40–220 или пустое поле.');return}
  const activity=String(document.getElementById('cardio-activity')?.value||drafts['cardio-activity']||'').trim();
  if(cardioType==='Другое'&&(activity.length<3||activity.length>100)){fail('Название активности: 3–100 символов.');return}
  const intensity=document.getElementById('cardio-intensity')?.value||'moderate';
  const saved=await send('cardio',{minutes:Number(m),avg_hr:p?Number(p):null,type:cardioType,...(cardioType==='Другое'?{activity,intensity}:{})});
  if(saved){modal='';cardioType='';typesOpen=false;drafts['cardio-min']='';drafts['cardio-hr']='';drafts['cardio-activity']='';drafts['cardio-intensity']='';if(date){dayRows=null;await loadDay()}draw()}
  else{const minutes=document.getElementById('cardio-min'),heartrate=document.getElementById('cardio-hr');if(minutes)minutes.value=m;if(heartrate)heartrate.value=p}
  return;
 }
 if(cmd==='week'){
  const selected=Number(element.dataset.week);
  if(!Number.isInteger(selected)||selected<1||selected>4)return;
  week=week===selected?0:selected;
  const card=document.getElementById('training-plan');
  if(card)card.outerHTML=trainingPlanCard();else draw();
  return;
 }
 if(cmd==='calendar'){calendarOpen=!calendarOpen;month=date.slice(0,7)||currentMonth();monthMarks=new Set();partialHistory();if(calendarOpen)await fetchMonthMarks();return}
 if(cmd==='prev-month'||cmd==='next-month'){const [y,m]=month.split('-').map(Number);month=new Date(Date.UTC(y,m-1+(cmd==='prev-month'?-1:1),1)).toISOString().slice(0,7);monthMarks=new Set();partialHistory();await fetchMonthMarks();return}
 if(cmd==='reset-date'){date='';dayRows=null;calendarOpen=false;partialHistory();return}
 if(cmd==='history-all'){modal='history';allRows=[];nextOffset=0;draw();await loadHistoryPage();return}
 if(cmd==='history-more'){await loadHistoryPage();return}
 if(cmd==='detail'){const id=Number(element.dataset.id);if(!Number.isSafeInteger(id))return;const result=await send('detail',{id});if(result){detail=result.detail;modal='detail';draw()}return}
});
setInterval(()=>{const element=document.getElementById('rest-count');if(!element)return;const seconds=Math.max(0,Math.ceil((restUntil-Date.now())/1000));if(!seconds){restUntil=0;restFor='';storeRestTimer();draw();return}element.textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`},500);
// Telegram's system safe area and its fullscreen content-controls area are
// distinct. Reserve both before drawing our own header or profile shortcut.
let fullscreenRequested=false;
function syncTelegramInsets(){
 const safe=tg?.safeAreaInset||{},content=tg?.contentSafeAreaInset||{};
 for(const side of ['top','bottom']){
  const device=Math.max(0,Math.min(Number(safe[side])||0,180));
  const controls=Math.max(0,Math.min(Number(content[side])||0,180));
  // On clients that report a late/zero content inset, protect the close/menu
  // overlay immediately when fullscreen is requested (until Telegram updates).
  const fallback=(side==='top'&&(tg?.isFullscreen||fullscreenRequested))?device+64:0;
  const inset=side==='top'?Math.max(device+controls,fallback):Math.max(device,controls);
  document.documentElement?.style?.setProperty('--fq-content-safe-'+side,Math.min(inset,240)+'px');
 }
}
if(token){
 try{
  tg.ready();tg.expand();syncTelegramInsets();
  if(typeof tg.onEvent==='function'){
   tg.onEvent('safeAreaChanged',syncTelegramInsets);
   tg.onEvent('contentSafeAreaChanged',syncTelegramInsets);
   tg.onEvent('fullscreenChanged',()=>{fullscreenRequested=!!tg.isFullscreen;syncTelegramInsets()});
   tg.onEvent('fullscreenFailed',()=>{fullscreenRequested=false;syncTelegramInsets()});
  }
  if(typeof tg.requestFullscreen==='function'&&
     (typeof tg.isVersionAtLeast!=='function'||tg.isVersionAtLeast('8.0'))){
   fullscreenRequested=true;
   syncTelegramInsets();
   try{tg.requestFullscreen()}catch(_e){fullscreenRequested=false;syncTelegramInsets()}
  }
 }catch(_e){/* Older Telegram clients stay expanded. */}
 send('state');
}else draw();
})();
