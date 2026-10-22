/* FORMIQ 38.2.0: readable titles, equipment form, two trial levels.
   Loaded after previous, working UX layers; avoid changing the embedded app. */
(()=>{
'use strict';
const previousApi = api;
const previousOnboarding382 = onboarding;
const previousExecute382 = execute;
const previousShow382 = show;
const previousPricing382 = renderPricing;
const previousCoach382 = renderCoach;
let equipmentDraft382 = null;
let equipmentSuggestion382 = null;

api = async function(action,data={}){
  if(action==='onboarding' && data.answers?.equipment==='homegear'){
    data.equipment_description = ($('fq_equipment_text')?.value ?? equipmentDraft382 ?? state?.equipment_description ?? '').trim();
  }
  return previousApi(action,data);
};

function installEquipmentForm(){
  const sel=$('a_equipment');
  if(!sel)return;
  const wrapper=sel.closest('.two') || sel.closest('.field');
  if(!wrapper)return;
  let section=$('fq_equipment_panel');
  if(!section){
    section=document.createElement('div');
    section.id='fq_equipment_panel';
    section.className='fq-equipment-panel';
    section.innerHTML='<div class="field"><label for="fq_equipment_text">Что есть для тренировок дома?</label>'+
      '<textarea id="fq_equipment_text" rows="3" maxlength="400" placeholder="Например: гантели 5 и 10 кг, эспандер, коврик"></textarea></div>'+
      '<label class="fq-equipment-consent"><input type="checkbox" id="fq_equipment_ai_consent">'+
      '<span>Разрешаю Yandex AI разобрать мой список инвентаря</span></label>'+
      '<button type="button" class="btn ghost slim" data-act="equipment-analyze">Разобрать с ИИ</button>'+
      '<div id="fq_equipment_preview" aria-live="polite"></div>';
    wrapper.insertAdjacentElement('afterend',section);
    const input=$('fq_equipment_text');
    input.value=equipmentDraft382 ?? state?.equipment_description ?? '';
    input.addEventListener('input',()=>{equipmentDraft382=input.value;equipmentSuggestion382=null;});
  }
  const toggle=()=>{
    section.hidden=sel.value!=='homegear';
    if(!section.hidden){
      const input=$('fq_equipment_text');
      if(input && document.activeElement!==input && equipmentDraft382!==null && input.value!==equipmentDraft382)
        input.value=equipmentDraft382;
    }
  };
  if(!sel.dataset.fqEquipmentBound){
    sel.addEventListener('change',toggle);
    sel.dataset.fqEquipmentBound='yes';
  }
  toggle();
}
onboarding=function(){
  previousOnboarding382();
  installEquipmentForm();
};

execute=async function(action){
  if(action==='equipment-analyze'){
    if(busy)return;
    const raw=$('fq_equipment_text')?.value.trim()||'';
    if(raw.length<3){notice('Перечисли оборудование своими словами','error');return;}
    if(!$('chk_age')?.checked){notice('Подтверди, что тебе исполнилось 18 лет','error');return;}
    if(!$('fq_equipment_ai_consent')?.checked){notice('Для анализа нужно отдельное согласие','error');return;}
    busy=true;
    const button=document.querySelector('[data-act="equipment-analyze"]');
    if(button){button.disabled=true;button.textContent='Разбираем…';}
    try{
      const result=await api('equipment_analyze',{text:raw,adult:true,privacy_ack:true});
      equipmentSuggestion382=(result.equipment?.items||[]).join(', ');
      if(!equipmentSuggestion382)throw new Error('Не удалось выделить оборудование');
      const preview=$('fq_equipment_preview');
      if(preview){
        preview.replaceChildren();
        const text=document.createElement('p');
        text.textContent='ИИ распознал: '+equipmentSuggestion382;
        const accept=document.createElement('button');
        accept.type='button';accept.dataset.act='equipment-apply';
        accept.className='btn ghost slim';accept.textContent='Использовать этот список';
        preview.append(text,accept);
      }
      notice('Проверь список. Он не сохранится без твоего подтверждения.','ok');
    }catch(err){notice(err.message||'Ошибка анализа','error');}
    finally{busy=false;if(button?.isConnected){button.disabled=false;button.textContent='Разобрать с ИИ';}}
    return;
  }
  if(action==='equipment-apply'){
    if(equipmentSuggestion382!==null){
      equipmentDraft382=equipmentSuggestion382;
      if($('fq_equipment_text'))$('fq_equipment_text').value=equipmentDraft382;
      const box=$('fq_equipment_preview');if(box)box.textContent='Список готов. Сохрани анкету, чтобы применить его к плану.';
    }
    return;
  }
  const outcome=await previousExecute382(action);
  if(action==='onboarding' && state?.profile_raw?.goal && !editingOnboarding)equipmentDraft382=null;
  return outcome;
};

renderPricing=function(){
  const chosen=state?.tier==='max'?'max':'comfort';
  return card('<div class="eyebrow">Два уровня FORMIQ · тестовый режим</div>'+
    '<p class="subtitle">Оплата не подключена. Стоимость и окончательное наполнение тарифов будут утверждены отдельно.</p>'+
    '<div class="tier-card '+(chosen==='comfort'?'chosen':'')+'">'+
    '<strong>FORMIQ Coach</strong>'+
    '<p class="small">ИИ-тренер, личная программа, полный дневник, своё кардио, история и собственные тренировки.</p>'+
    (chosen==='comfort'?'<div class="small">✓ Выбран для тестирования</div>':(state.tier_demo?btn('tier-comfort','Попробовать Coach','ghost slim'):''))+
    '</div><div class="tier-card '+(chosen==='max'?'chosen':'')+'">'+
    '<strong>FORMIQ 360</strong>'+
    '<p class="small">Всё из Coach. Garmin Connect и FatSecret появятся только после работающей авторизации и синхронизации.</p>'+
    (chosen==='max'?'<div class="small">✓ Выбран для тестирования</div>':(state.tier_demo?btn('tier-max','Попробовать 360','ghost slim'):''))+
    '</div><div class="small">Никаких автоматических списаний.</div>');
};
renderCoach=function(){
  if(!state)return;
  if(state.tier==='max')return previousCoach382();
  const old=state.tier;
  try{state.tier='max';return previousCoach382();}
  finally{state.tier=old;}
};
show=function(markup){
  previousShow382(markup);
  const foot=$('fq-version-footer');
  if(foot)foot.textContent='FORMIQ 38.2.0';
};
})();