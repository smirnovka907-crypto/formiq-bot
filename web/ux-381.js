/* FORMIQ 38.1 UX upgrade: load AFTER the 38.0 inline app script.
   This file has no API credentials and intentionally preserves existing flows. */
(()=>{
'use strict';
const oldOnboarding=onboarding,oldRenderProfile=renderProfile,oldExecute=execute;
const providerTheme=()=>{
  if(themeMode==='graphite'||themeMode==='dark')return 'dark';
  if(themeMode==='pearl'||themeMode==='light'||themeMode==='blue'||themeMode==='rose')return 'light';
  return TG?.colorScheme==='dark'||(!TG?.colorScheme&&window.matchMedia?.('(prefers-color-scheme: dark)').matches)?'dark':'light';
};
applyTheme=function(){
  const actual=providerTheme();
  document.documentElement.dataset.theme=actual;
  document.documentElement.dataset.fqTheme=actual==='dark'?'graphite':'pearl';
  document.documentElement.style.colorScheme=actual;
  const bg=actual==='dark'?'#000000':'#f5f5f7';
  try{TG?.setBackgroundColor?.(bg);TG?.setHeaderColor?.(bg)}catch(_){}
};
applyTheme();

refreshNav=function(){
  const onboardingNeeded=!state?.agreed||!state?.profile_raw?.goal||state?.needs_health_profile;
  const choices=onboardingNeeded?[]:[['workout','Сегодня'],['plan','План'],['progress','Прогресс']];
  const nav=$('tabs');nav.style.display=onboardingNeeded?'none':'grid';
  nav.style.gridTemplateColumns='repeat(3,minmax(0,1fr))';
  nav.innerHTML=choices.map(([id,title])=>
    `<button type="button" data-tab="${id}" aria-current="${tab===id?'page':'false'}" class="${tab===id?'sel':''}">${title}</button>`).join('');
  $('profileLink').style.display=onboardingNeeded?'none':'inline-flex';
};

headerCard=function(){
  const cal=state.calendar||[];
  const upcoming=cal.find(x=>x.status==='planned');
  const title=upcoming?.title||state.next_title||'Ближайшая тренировка';
  const when=upcoming?.date?dateRus(upcoming.date):'Сегодня';
  const safeCount=value=>Number.isFinite(Number(value))?Math.max(0,Math.floor(Number(value))):0;
  return `<section class="today-hero">
      <div class="eyebrow">${e(when)}</div>
      <h1 class="hero-name">${e(title)}</h1>
      <p class="hero-meta">${e(state.profile_raw?.minutes||30)} минут · твой план</p>
      <div class="hero-actions">
        ${btn('start-normal','Начать тренировку')}
        <button type="button" class="text-link" data-act="start-tired">Сегодня меньше сил? Облегчить занятие</button>
      </div>
    </section>
    <div class="fq-dashboard-heading"><strong>Твой прогресс</strong>
      <button type="button" class="fq-dashboard-link" data-tab="progress">Подробнее →</button>
    </div>
    <div class="fq-dashboard-metrics">
      <div class="fq-stat"><div class="fq-stat-number">${safeCount(state.stats?.last7)}</div><div class="fq-stat-label">Тренировок за 7 дней</div></div>
      <div class="fq-stat"><div class="fq-stat-number">${safeCount(state.stats?.cardio7)}</div><div class="fq-stat-label">Минут кардио за 7 дней</div></div>
    </div>
    <div class="fq-ai-entry">${cell('coach-open','✦ Спросить ИИ-тренера')}</div>
    ${state.tier!=='start'?`<div class="fq-ai-entry">${cell('new-manual','Создать свою тренировку')}</div>`:''}
    <div class="fq-feedback-link">${cell('feedback-open','Отзывы и предложения','→')}</div>`;
};

renderProfile=function(){
  oldRenderProfile();
  const grid=document.querySelector('.fq-theme-grid');
  if(!grid)return;
  const modes=[['auto','Система'],['pearl','Светлая'],['graphite','Тёмная']];
  grid.innerHTML=modes.map(([key,label])=>
    `<button type="button" data-theme-mode="${key}" class="fq-theme-option ${themeMode===key?'sel':''}" aria-pressed="${themeMode===key?'true':'false'}">${label}</button>`).join('');
  const hint=grid.previousElementSibling;
  if(hint&&hint.classList.contains('subtitle'))hint.textContent='Автоматическая тема повторяет настройки телефона или Telegram.';
};

onboarding=function(){
  oldOnboarding();
  const extraRow=$('on_pain')?.closest('.two');
  const parent=extraRow?.parentElement;
  if(extraRow&&parent&&!parent.querySelector('#fq_optional_health')){
    const details=document.createElement('details');
    details.id='fq_optional_health';
    details.className='fq-optional-health';
    const summary=document.createElement('summary');
    summary.textContent='Дополнительные сведения об ограничениях';
    details.appendChild(summary);
    details.appendChild(extraRow);
    const safety=Array.from(parent.querySelectorAll('details.fq-health-panel')).find(x=>x.textContent.includes('Важные детали безопасности'));
    if(safety){safety.open=false;safety.querySelector('summary').textContent='Особые состояния, требующие осторожности';details.appendChild(safety);}
    parent.appendChild(details);
  }
};

showHealthAnalysis=function(a){
  const area=$('health_analysis_result');if(!area)return;
  if(!a||!Array.isArray(a.affected))return;
  const affected=a.affected.map(key=>healthRegions.find(x=>x[0]===key)?.[1]||key).join(', ')||'Не удалось однозначно определить';
  const pending=!!a.needs_clarification;
  area.innerHTML=`<div class="fq-ai-result" role="status">
    <strong>ИИ выделил особенности</strong>
    <p>${e(a.short_summary||affected)}</p>
    <div class="small">Учитываем: ${e(affected)}</div>
    ${pending?`<div class="fq-health-followup"><label for="fq_health_followup">Уточни, пожалуйста: ${e(a.clarification_question||'Расскажи немного подробнее о симптомах')}</label>
    <textarea id="fq_health_followup" rows="3" maxlength="350" placeholder="Например: боль возникает только при поднятии руки..."></textarea>
    ${btn('health-refine','Отправить уточнение','ghost slim')}</div>`:
    `<label class="fq-health-confirm fq-result-confirm"><input id="fq_confirm_analysis" type="checkbox">
    <span>Проверил(а) результат. Учитывать при выборе упражнений.</span></label>`}
  </div>`;
  if(a.pain_score!==null&&a.pain_score!==undefined&&$('on_pain'))$('on_pain').value=a.pain_score;
  if(a.symptom_course&&a.symptom_course!=='none'&&$('on_course'))$('on_course').value=a.symptom_course;
  if(a.danger_signs&&$('on_danger'))$('on_danger').checked=true;
};

const networkActions=new Set(['start-normal','start-tired','save','onboarding','save-profile',
 'manual-save','manual-start','finish','skip','reschedule','save-custom','feedback-send','ai-send',
 'health-analyze','health-refine','cardio','food-analyze']);
execute=async function(action){
 if(action==='coach-open'){setTab('coach');return;}
 if(action==='health-refine'){
   if(busy)return;
   const answer=$('fq_health_followup')?.value.trim()||'';
   const current=$('health_description')?.value.trim()||'';
   if(answer.length<5){notice('Добавь несколько слов об особенностях боли','error');return;}
   if(!current||!healthAnalysis){notice('Сначала опиши ограничения','error');return;}
   const combined=current+'\nУточнение: '+answer;
   if(combined.length>800){notice('Описание слишком длинное. Сократи исходный текст.','error');return;}
   const button=document.querySelector('[data-act="health-refine"]');
   busy=true;
   if(button){button.disabled=true;button.textContent='Анализируем…';button.classList.add('fq-wait');}
   try{
     notice();
     const response=await api('health_analyze',{text:combined,privacy_ack:true,adult:true});
     healthDescription=combined;healthAnalysis=response.analysis;
     $('health_description').value=combined;
     showHealthAnalysis(healthAnalysis);
     notice(healthAnalysis.needs_clarification?'Добавь ещё уточнение, чтобы мы не сделали опасных предположений.':'Проверь результат и подтверди его.','ok');
   }catch(err){notice(err.message,'error');}
   finally{busy=false;if(button?.isConnected){button.disabled=false;button.classList.remove('fq-wait');button.textContent='Отправить уточнение';}}
   return;
 }
 if(action==='onboarding'){
   const status=document.querySelector('input[name="fq_limit_status"]:checked')?.value;
   const pain=$('on_pain')?.value.trim(),course=$('on_course')?.value;
   if(status==='yes'&&(!pain||!course)){
     const detail=$('fq_optional_health');
     if(detail)detail.open=true;
     notice('При ограничениях уточни степень и характер симптомов: это нужно для безопасного выбора упражнений.','error');
     $('on_pain')?.focus();
     return;
   }
   if(status==='yes'&&healthAnalysis?.needs_clarification){
     $('fq_health_followup')?.focus();
     notice('Сначала ответь на уточнение ИИ или выбери ограничения вручную.','error');return;
   }
 }
 if(busy)return;
 const button=networkActions.has(action)?document.querySelector(`[data-act="${action}"]`):null;
 const before=button?.textContent;
 if(button){button.disabled=true;button.classList.add('fq-wait');button.textContent='Выполняется…';}
 try{return await oldExecute(action);}
 finally{
   if(button?.isConnected){
     button.disabled=false;button.classList.remove('fq-wait');button.textContent=before;
   }
 }
};
})();
