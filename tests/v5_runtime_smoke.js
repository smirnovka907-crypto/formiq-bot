'use strict';
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const js=fs.readFileSync('web/v5-live.js','utf8');
class FakeFormData{
 constructor(){this.data=new Map()}
 append(name,value){this.data.set(name,value)}
}


function createClient(auth=true,shared={}){
 const requests=[],handlers={},fields=new Map(),failActions=new Set(),staleActions=new Set();
 let html='';
 const root={get innerHTML(){return html},set innerHTML(value){html=value;for(const field of fields.values()){const tail=html.split('id="'+field.id+'"')[1];const tag=tail?.split('>')[0];field.value=tag?.match(/value="([^"]*)"/)?.[1]??''}},addEventListener(name,fn){handlers[name]=fn}};
 const doc={
  getElementById(id){return id==='app'?root:fields.get(id)||null},
  querySelector(){return null},
  activeElement:null
 };
 let workout=shared.workout||null;
 const temporary=shared.storage||(shared.storage=new Map());
 const viewportHandlers={};
 const scrollMoves=[];
 let metrics={age:34,height_cm:181,weight_kg:82};
 const client={
  root,handlers,fields,requests,scrollMoves,viewportHandlers,
  failOnce(action){failActions.add(action)},
  staleOnce(action){staleActions.add(action)},
  async fetch(url,opts){
   if(url==='/mini/report'){
    assert.equal(opts.method,'POST');
    assert.equal(opts.headers['X-Formiq-Init'],'signed-for-test');
    assert.equal(opts.body.data.get('consent'),'yes','No upload without consent');
    assert.equal(opts.body.data.get('report')?.name,'report.csv');
    requests.push({action:'nutrition-report'});
    return {ok:true,status:200,async json(){return {ok:true,answer:'В отчёте указано 1900 ккал.'}}};
   }
   assert.equal(url,'/mini/api');
   assert.equal(opts.method,'POST');
   assert.equal(opts.headers['X-Formiq-Init'],'signed-for-test');
   const p=JSON.parse(opts.body);requests.push(p);
   if(failActions.delete(p.action))return {ok:false,status:503,async json(){return {ok:false,error:'Временная ошибка API'}}};
   if(staleActions.delete(p.action)){
    workout={...workout,done:1,rest_remaining_seconds:0,current:{...workout.current,set_no:2}};
    shared.workout=workout;
    return {ok:false,status:400,async json(){return {ok:false,error:'Этот подход уже изменился. Обнови тренировку'}}};
   }
   let response;
   const state=()=>({
    agreed:true,profile_raw:{goal:'general'},needs_health_profile:false,error:null,
    profile:{goal:'Поддерживать форму'},metrics:{...metrics},tier_name:'Тестовый доступ',
    workout,history:[{id:8,date:'23.10.2026',title:'Силовая'}],
    plan_names:['Ноги и пресс'],next_day:'A',cycle_start:'2026-10-19',
    plan:[[{name:'Жим ногами',sets:3,low:10,high:12}]],
    calendar:[{id:2,week:1,day:'A',title:'Ноги и пресс',date:'2026-10-23',date_ru:'23.10.2026',status:'planned'}],
    stats:{total:1,sets:6}});
   if(p.action==='state')response={ok:true,data:state()};
   else if(p.action==='start'){
    assert.ok(['normal','tired'].includes(p.mood));
    workout={id:9,done:0,total:2,finished:false,title:'Ноги и пресс',current:{name:'Жим ногами',position:0,set_no:1,set_count:2,low:10,high:12,unit:'reps',rest_seconds:90,tip:'Двигай плавно'}};
    shared.workout=workout;
    response={ok:true,patch:{workout}};
   }else if(p.action==='record'){
    workout={...workout,done:1,rest_remaining_seconds:89,current:{...workout.current,set_no:2}};
    shared.workout=workout;
    response={ok:true,patch:{workout}};
   }else if(p.action==='history_month')response={ok:true,dates:['2026-10-23'],month:p.month};
   else if(p.action==='history_page')response={ok:true,history:[{id:8,date:'23.10.2026',title:'Силовая'}],next_offset:null};
   else if(p.action==='detail')response={ok:true,detail:{title:'Силовая',date:'23.10.2026',items:[{name:'Жим ногами',result:'12 повт. · 60 кг'}]}};
   else if(p.action==='cardio'){assert.equal(p.type,'Велосипед');response={ok:true,data:state()};}
   else if(p.action==='health_analyze'){
     assert.equal(p.adult,true);assert.equal(p.privacy_ack,true);
     response={ok:true,analysis:{affected:['knee'],pain_score:3,symptom_course:'stable',danger_signs:false,short_summary:'Беспокоит колено'}};
    }
    else if(p.action==='onboarding'){
     assert.equal(p.terms,true);assert.equal(p.privacy,true);assert.equal(p.health,true);
     assert.equal(p.answers.age_group,'adult');
     assert.ok(p.metrics.age>=18);
     assert.ok(Array.isArray(p.health_profile.affected));
     response={ok:true,data:state()};
    }
    else if(p.action==='save_metrics'){
    assert.ok(Object.keys(p.metrics).every(k=>['age','height_cm','weight_kg'].includes(k)));
    Object.assign(metrics,p.metrics);response={ok:true,patch:{metrics:{...metrics},zones:[]}};
   }
   else if(p.action==='finish'){workout=null;shared.workout=null;response={ok:true,data:state()}}
   else if(p.action==='skip')response={ok:true,patch:{workout}};
   else throw Error('Unexpected action: '+p.action);
   return {ok:true,status:200,async json(){return response}};
  }
 };
 const context={
  document:doc,
  window:{Telegram:{WebApp:{initData:auth?'signed-for-test':'',ready(){},expand(){},...(shared.fullscreen?{isVersionAtLeast(){return true},requestFullscreen(){shared.fullscreenCalls=(shared.fullscreenCalls||0)+1},onEvent(){}}:{})}},scrollTo(){},scrollBy(data){scrollMoves.push(data.top)},visualViewport:{offsetTop:0,addEventListener(n,fn){viewportHandlers[n]=fn}},sessionStorage:{getItem(k){return temporary.get(k)||null},setItem(k,v){temporary.set(k,v)},removeItem(k){temporary.delete(k)}}},
  fetch:client.fetch,
  setTimeout(fn){return 1},clearTimeout(){},setInterval(fn){return 1},
  AbortController,Date,Set,Number,String,Array,Map,Object,RegExp,Math,FormData:FakeFormData,
 };
 vm.runInNewContext(js,context,{filename:'web/v5-live.js',timeout:2000});
 client.click=async(dataset)=>{
  const target={closest(sel){return sel==='button'?{dataset}:null}};
  await handlers.click({target});
 };
 client.input=(id,value)=>{const field={id,value};fields.set(id,field);handlers.input?.({target:field})};
 return client;
}
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))};

async function run(){
 const blocked=createClient(false);
 assert.match(blocked.root.innerHTML,/Открой из Telegram/);
 assert.equal(blocked.requests.length,0);
 const restored={storage:new Map(),workout:{id:71,done:1,total:3,finished:false,title:'Зал',
   rest_remaining_seconds:47,current:{name:'Жим ногами',position:0,set_no:2,set_count:3,
     low:10,high:12,unit:'reps',rest_seconds:120,tip:'Плавно'}}};
 const serverResumed=createClient(true,restored);
 await settle();
 assert.match(serverResumed.root.innerHTML,/rest-count/,'Server time restores rest with empty sessionStorage');
 await serverResumed.click({cmd:'rest-skip'});
 assert.doesNotMatch(serverResumed.root.innerHTML,/rest-count/,'User can skip rest');
 const reopened=createClient(true,restored);
 await settle();
 assert.doesNotMatch(reopened.root.innerHTML,/rest-count/,'Skipped rest persists across reload');
 const staleCase=createClient(true,{storage:new Map()});
 await settle();
 await staleCase.click({cmd:'mood'});
 await staleCase.click({cmd:'start-normal'});
 staleCase.input('reps','12');staleCase.input('weight','60');
 staleCase.staleOnce('record');
 await staleCase.click({cmd:'record'});
 assert.match(staleCase.root.innerHTML,/Дневник обновлён/);
 assert.match(staleCase.root.innerHTML,/Подход 2 из 2/);
 assert.match(staleCase.root.innerHTML,/id="reps"[^>]*value=""/);
 assert.match(staleCase.root.innerHTML,/id="weight"[^>]*value=""/);
 assert.equal(staleCase.requests.filter(x=>x.action==='record').length,1,'Retry error does not auto-submit next approach');
 const shared={storage:new Map()};
 const app=createClient(true,shared);
 await settle();
 assert.match(app.root.innerHTML,/Начать тренировку/);
 assert.ok(app.requests.find(x=>x.action==='state'));
 await app.click({cmd:'mood'});
 assert.match(app.root.innerHTML,/Самочувствие перед началом/);
 await app.click({cmd:'start-normal'});
 assert.match(app.root.innerHTML,/Жим ногами/);
 assert.match(app.root.innerHTML,/id="reps"[^>]*value=""/);
 app.input('reps','12');app.input('weight','60');
 await app.click({nav:'profile'});
 await app.click({nav:'home'});
 assert.match(app.root.innerHTML,/id="reps"[^>]*value="12"/);
 assert.match(app.root.innerHTML,/id="weight"[^>]*value="60"/);
 app.failOnce('record');
 await app.click({cmd:'record'});
 assert.equal(app.fields.get('reps').value,'12','unsaved repetitions retained after error');
 assert.equal(app.fields.get('weight').value,'60','unsaved weight retained after error');
 assert.match(app.root.innerHTML,/Временная ошибка API/);
 await app.click({cmd:'record'});
 assert.ok(app.requests.some(x=>x.action==='record'&&x.reps===12&&x.weight===60&&x.expected_workout===9&&x.expected_position===0&&x.expected_set===1));
 assert.match(app.root.innerHTML,/rest-count/);
 assert.ok(shared.storage.has('formiq_v5_rest_countdown'),'rest countdown stored temporarily');
 const resumed=createClient(true,shared);
 await settle();
 assert.match(resumed.root.innerHTML,/rest-count/,'rest restored when Mini App reloads');
 await resumed.click({cmd:'rest-skip'});
 assert.equal(JSON.parse(shared.storage.get('formiq_v5_rest_countdown')).skippedFor,'9:0:2','rest skip persisted for current set');
 await app.click({cmd:'rest-skip'});
 assert.match(app.root.innerHTML,/Подход 2 из 2/);
 assert.match(app.root.innerHTML,/id="reps"[^>]*value=""/);
 assert.match(app.root.innerHTML,/id="weight"[^>]*value=""/);
 await app.click({cmd:'finish-confirm'});
 await app.click({cmd:'finish'});
 assert.ok(app.requests.some(x=>x.action==='finish'));
 await app.click({nav:'home'});
 await app.click({cmd:'cardio-add'});
 await app.click({cmd:'cardio-types'});
 await app.click({cmd:'cardio-type',type:'Велосипед'});
 app.input('cardio-min','60');app.input('cardio-hr','120');
 await app.click({cmd:'cardio-types'});
 await app.click({cmd:'cardio-type',type:'Бег'});
 assert.match(app.root.innerHTML,/id="cardio-min"[^>]*value="60"/);
 assert.match(app.root.innerHTML,/id="cardio-hr"[^>]*value="120"/);
 await app.click({cmd:'cardio-types'});
 await app.click({cmd:'cardio-type',type:'Велосипед'});
 app.failOnce('cardio');
 await app.click({cmd:'cardio'});
 assert.equal(app.fields.get('cardio-min').value,'60','unsaved cardio duration retained');
 assert.equal(app.fields.get('cardio-hr').value,'120','unsaved average HR retained');
 await app.click({cmd:'cardio'});
 assert.ok(app.requests.some(x=>x.action==='cardio'&&x.type==='Велосипед'&&x.minutes===60));
 assert.doesNotMatch(app.root.innerHTML,/id="cardio-min"/,"Cardio form closes after save");
 await app.click({cmd:'cardio-add'});
 assert.match(app.root.innerHTML,/id="cardio-min"[^>]*value=""/);
 assert.match(app.root.innerHTML,/id="cardio-hr"[^>]*value=""/);
 await app.click({cmd:'close'});
 assert.equal((app.root.innerHTML.match(/class="nav-item /g)||[]).length,3,'Only three bottom nav buttons');
  await app.click({cmd:'plan-open'});
 assert.match(app.root.innerHTML,/19\.10\.2026 — 25\.10\.2026/,'Plan period must show all 7 days');
  await app.click({cmd:'plan-back'});
  assert.match(app.root.innerHTML,/Начать тренировку/,'Return from plan to workouts');
 await app.click({nav:'progress'});
 await app.click({nav:'profile'});
 assert.match(app.root.innerHTML,/data-nav="home"/,'User must be able to exit profile without Back');
 assert.match(app.root.innerHTML,/Изменить параметры/);
 await app.click({cmd:'profile-metrics-edit'});
 assert.match(app.root.innerHTML,/id="profile-age"[^>]*value="34"/);
 app.input('profile-age','34');app.input('profile-height_cm','181');app.input('profile-weight_kg','84,5');
 const totalStatesBefore=app.requests.filter(x=>x.action==='state').length;
 await app.click({cmd:'profile-metrics-save'});
 assert.equal(app.requests.filter(x=>x.action==='state').length,totalStatesBefore,'metric patch should avoid reloading full dashboard');
 const metricSaves=app.requests.filter(x=>x.action==='save_metrics');
 assert.equal(metricSaves.length,1);
 assert.deepEqual(metricSaves[0].metrics,{weight_kg:84.5},'Saving weight must not alter age or height');
 assert.match(app.root.innerHTML,/84.5/);
 assert.match(app.root.innerHTML,/Изменения сохранены/);
 await app.click({cmd:'profile-metrics-edit'});
 app.input('profile-age','10');app.input('profile-height_cm','181');app.input('profile-weight_kg','84.5');
 await app.click({cmd:'profile-metrics-save'});
 assert.equal(app.requests.filter(x=>x.action==='save_metrics').length,1,'Invalid age must not reach API');
 assert.match(app.root.innerHTML,/Проверь допустимые значения/);
 await app.click({cmd:'profile-metrics-cancel'});
 assert.doesNotMatch(app.root.innerHTML,/id="profile-age"/);
 const inputField={id:'cardio-min',closest(){return {getBoundingClientRect(){return {top:210}}}}};
 app.fields.set('cardio-min',inputField);
 app.handlers.focusin({target:inputField});
 assert.equal(typeof app.viewportHandlers.resize,'function','Android viewport resize handler is present');
 // The field may be hidden in profile, but the helper must remain safely callable.
 app.viewportHandlers.resize();

 await app.click({nav:'progress'});
 assert.match(app.root.innerHTML,/История тренировок/);
 await app.click({cmd:'calendar'});
 assert.ok(app.requests.find(x=>x.action==='history_month'&&/^\d{4}-\d{2}$/.test(x.month)));
 const selected=app.root.innerHTML;
 assert.match(selected,/has-entry/);
 await app.click({date:'2026-10-23'});
 assert.ok(app.requests.some(x=>x.action==='history_page'&&x.date==='2026-10-23'));
 await app.click({cmd:'history-all'});
 assert.ok(app.requests.some(x=>x.action==='history_page'&&x.offset===0));
 await app.click({cmd:'detail',id:'8'});
 assert.ok(app.requests.some(x=>x.action==='detail'&&x.id===8));
 assert.match(app.root.innerHTML,/12 повт/);
 await app.click({nav:'food'});
 assert.match(app.root.innerHTML,/nutrition-file/);
 assert.match(app.root.innerHTML,/nutrition-consent/);
 const reportCount=()=>app.requests.filter(x=>x.action==='nutrition-report').length;
 app.fields.set('nutrition-error',{id:'nutrition-error',textContent:''});
 await app.click({cmd:'nutrition-analyze'});
 assert.equal(reportCount(),0,'No file means no API call');
 assert.match(app.fields.get('nutrition-error').textContent,/Выбери/);
 app.fields.set('nutrition-file',{id:'nutrition-file',files:[{name:'report.csv',size:500,type:'text/csv'}]});
 app.fields.set('nutrition-consent',{id:'nutrition-consent',checked:false});
 await app.click({cmd:'nutrition-analyze'});
 assert.equal(reportCount(),0,'No consent means no API call');
 assert.match(app.fields.get('nutrition-error').textContent,/Подтверди согласие/);
 app.fields.get('nutrition-consent').checked=true;
 await app.click({cmd:'nutrition-analyze'});
 assert.equal(reportCount(),1,'One report uploaded with consent');
 assert.match(app.root.innerHTML,/1900 ккал/);
 const polished={fullscreen:true};
  const ux=createClient(true,polished);await settle();
  assert.equal(polished.fullscreenCalls,1,'Supported Telegram clients request true fullscreen');
  assert.match(ux.root.innerHTML,/Тренировки/);
   assert.equal((ux.root.innerHTML.match(/class="nav-item /g)||[]).length,3,'Fullscreen has three bottom buttons');
  await ux.click({cmd:'plan-open'});
  assert.match(ux.root.innerHTML,/Твой план/);
  assert.match(ux.root.innerHTML,/week-range/);
  await ux.click({nav:'profile'});
  await ux.click({cmd:'onboard-open'});
  assert.match(ux.root.innerHTML,/data-onboard-pick="goal"/,'Goal uses approved choice buttons');
   assert.match(ux.root.innerHTML,/data-onboard-pick="equipment"/,'Equipment uses approved choice buttons');
   assert.match(ux.root.innerHTML,/id="onboard-duration"/,'Duration uses approved slider');
   assert.doesNotMatch(ux.root.innerHTML,/href="\/mini\/legacy"/,'Editing stays in v5');
   await ux.click({cmd:'onboard-save'});
   assert.equal(ux.requests.filter(x=>x.action==='onboarding').length,0,'No consent, no save');
   for(const key of ['adult','terms','privacy','health'])
     ux.handlers.change({target:{dataset:{onboard:key},type:'checkbox',checked:true}});
   ux.handlers.change({target:{dataset:{onboard:'limitation'},type:'select-one',value:'yes'}});
   ux.handlers.input({target:{dataset:{onboard:'description'},type:'textarea',value:'Беспокоит колено при приседаниях'}});
   await ux.click({cmd:'onboard-save'});
   assert.equal(ux.requests.filter(x=>x.action==='onboarding').length,0,'Never silently discard unprocessed health description');
   assert.match(ux.root.innerHTML,/Описание не подтверждено/);
   ux.handlers.input({target:{dataset:{onboard:'description'},type:'textarea',value:''}});
   ux.handlers.change({target:{dataset:{area:'knee'},type:'checkbox',checked:true}});
   ux.handlers.change({target:{dataset:{onboard:'course'},type:'select-one',value:'stable'}});
   ux.handlers.input({target:{dataset:{onboard:'minutes'},type:'range',value:'50'}});
   await ux.click({onboardPick:'sex',value:'female'});
   await ux.click({cmd:'onboard-save'});
   const edits=ux.requests.filter(x=>x.action==='onboarding');
   assert.equal(edits.length,1,'Manual health restrictions sent through authenticated onboarding');
   assert.equal(edits[0].metrics.weight_kg,82);
   assert.equal(edits[0].metrics.sex,'female');
   assert.equal(edits[0].answers.minutes,'50');
   assert.deepEqual(Array.from(edits[0].health_profile.affected),['knee']);
   assert.match(ux.root.innerHTML,/Тренировки/,'Returns to v5 after profile save');
  
   const ai=createClient(true,{storage:new Map()});await settle();
   await ai.click({nav:'profile'});await ai.click({cmd:'onboard-open'});
   for(const key of ['adult','terms','privacy','health'])
     ai.handlers.change({target:{dataset:{onboard:key},type:'checkbox',checked:true}});
   ai.handlers.change({target:{dataset:{onboard:'limitation'},type:'select-one',value:'yes'}});
   ai.handlers.input({target:{dataset:{onboard:'description'},type:'textarea',value:'Беспокоит колено после пробежки'}});
   await ai.click({cmd:'onboard-ai'});
   assert.equal(ai.requests.filter(x=>x.action==='health_analyze').length,0,'AI requires separate opt-in');
   ai.handlers.change({target:{dataset:{onboard:'aiConsent'},type:'checkbox',checked:true}});
   await ai.click({cmd:'onboard-ai'});
   assert.equal(ai.requests.filter(x=>x.action==='health_analyze').length,1);
   assert.match(ai.root.innerHTML,/Проверь разбор ИИ/);
   await ai.click({cmd:'onboard-save'});
   assert.equal(ai.requests.filter(x=>x.action==='onboarding').length,0,'AI result must be reviewed');
   ai.handlers.change({target:{dataset:{onboard:'aiReviewed'},type:'checkbox',checked:true}});
   await ai.click({cmd:'onboard-save'});
   const aiSaves=ai.requests.filter(x=>x.action==='onboarding');
   assert.equal(aiSaves.length,1,'Reviewed AI result can be saved');
   assert.equal(aiSaves[0].health_profile.pain_score,3);
   console.log('PASS v5 signed API, three tabs, nested plan, native onboarding, fullscreen fallback, workout, history and consent');
}
run().catch(e=>{console.error(e);process.exitCode=1});
