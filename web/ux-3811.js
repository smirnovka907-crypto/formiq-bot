/* FORMIQ 38.1.1: single health narrative, always-visible feedback and version. */
(()=>{
'use strict';
const VERSION_LABEL='38.1.1';
const previousOnboarding=onboarding;
const previousExecute=execute;
const previousRefreshNav=refreshNav;
const previousHeaderCard=headerCard;
const previousShow=show;
const detection=[
 ['heart',/сердц|сердечн|аритми|гипертони|давлени|стенокард|боль\s+в\s+груд/i],
 ['breathing',/дыхани|дышат|одышк|астм|бронх/i],
 ['shoulder',/плеч|ротатор|лопатк/i],
 ['back',/спин|поясниц|позвон|сколиоз/i],
 ['knee',/колен|надколен|мениск/i],
 ['hip',/бедр|тазобедр|тазов/i],
 ['wrist',/запяст|кист[ьи]|ладон/i],
 ['ankle',/голеност|стоп[аеуы]|щиколот/i],
 ['neck',/ше[ияю]|шейн/i],
 ['other',/операц|травм|перелом|реабилитац|ограничен/i],
];
const redFlags=/боль\s+в\s+груд|обморок|потер[яи]\s+сознани|сильн\S*\s+одышк|резк\S*\s+ухудш/i;

function displayHealth(){
 const zone=$('fq-health-description-box');
 if(!zone)return;
 zone.hidden=false;
 document.querySelector('.fq-health-choices')?.setAttribute('hidden','');
 const oldGrid=$('health_fallback');
 if(oldGrid)oldGrid.hidden=true;
 const optional=$('fq_optional_health');
 if(optional)optional.hidden=true;
 // The fields remain mounted for compatibility with the existing validated API.
 const input=$('health_description');
 const label=input?.closest('.field')?.querySelector('label');
 if(label)label.textContent='Ограничения и самочувствие (если есть)';
 if(input)input.placeholder='Например: болит плечо при отжиманиях, поясница после долгой ходьбы.';
 let helper=$('fq-health-hint');
 if(!helper){
  helper=document.createElement('p');
  helper.id='fq-health-hint';helper.className='subtitle fq-health-hint';
  helper.textContent='Нечего сообщить? Оставь поле пустым. Если есть боли или ограничения — опиши своими словами. Мы учтём их при подборе нагрузки.';
  zone.insertBefore(helper,zone.firstChild);
 }
 const consent=$('health_ai_consent')?.closest('label');
 const aiButton=zone.querySelector('[data-act="health-analyze"]');
 function sync(){
  const raw=input?.value.trim()||'';
  const hasText=raw.length>0;
  if(consent)consent.hidden=!hasText;
  if(aiButton)aiButton.hidden=!hasText;
  const radio=document.querySelector('input[name="fq_limit_status"][value="'+(hasText||((state.health_profile?.affected||[]).length>0)?'yes':'none')+'"]');
  if(radio)radio.checked=true;
 }
 input?.addEventListener('input',()=>{
  if(healthAnalysis&&input.value.trim()!==healthDescription){
   healthAnalysis=null;
   $('health_analysis_result').textContent='';
  }
  sync();
 });
 sync();
 const card=zone.closest('.card');
 if(card){
  const eyebrow=card.querySelector('.eyebrow');
  if(eyebrow)eyebrow.textContent='03 · ОСОБЕННОСТИ';
 }
}
onboarding=function(){
 previousOnboarding();
 displayHealth();
};

function prepareHealthSubmission(){
 const input=$('health_description');
 if(!input)return;
 const raw=input.value.trim();
 const previously=(state?.health_profile?.affected||[]);
 const hasSaved=previously.length>0||!!state.health_profile?.danger_signs;
 const radio=document.querySelector('input[name="fq_limit_status"][value="'+(raw||hasSaved?'yes':'none')+'"]');
 if(radio)radio.checked=true;
 if(!raw)return;
 if(!healthAnalysis||raw!==healthDescription){
  healthAnalysis=null;healthDescription='';
  const regions=detection.filter(([name,pattern])=>pattern.test(raw)&&name!=='other').map(([name])=>name);
  // Ambiguous complaints stay conservatively blocked, never assumed healthy.
  if(!regions.length)regions.push('other');
  document.querySelectorAll('[data-lim]').forEach(el=>{el.checked=regions.includes(el.dataset.lim)});
 }
 const pain=$('on_pain'), course=$('on_course');
 if(pain&&!pain.value.trim())pain.value='0';
 if(course&&!course.value)course.value='recent';
 if(redFlags.test(raw)&&$('on_danger'))$('on_danger').checked=true;
}
execute=async function(action){
 if(action==='onboarding')prepareHealthSubmission();
 return previousExecute(action);
};

refreshNav=function(){
 previousRefreshNav();
 const nav=$('tabs');
 if(!nav)return;
 let quick=$('fq-feedback-quick');
 if(!quick){
  quick=document.createElement('div');
  quick.id='fq-feedback-quick';
  nav.insertAdjacentElement('afterend',quick);
 }
 const onMain=!editingOnboarding&&state?.agreed&&state?.profile_raw?.goal&&!feedbackMode&&tab==='workout';
 quick.hidden=!onMain;
 if(onMain)quick.innerHTML='<button type="button" class="fq-feedback-quick-button" data-act="feedback-open">💬 Отзывы и предложения <span aria-hidden="true">→</span></button>';
 else quick.innerHTML='';
};

headerCard=function(){
 const html=previousHeaderCard();
 return html.replace(/<div class="fq-feedback-link">[\s\S]*?<\/div>/,'');
};

show=function(markup){
 previousShow(markup+'<footer id="fq-version-footer" aria-label="Версия приложения">FORMIQ '+VERSION_LABEL+'</footer>');
};
})();
