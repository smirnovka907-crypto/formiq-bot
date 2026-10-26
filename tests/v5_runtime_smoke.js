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
 const requests=[],handlers={},fields=new Map(),failActions=new Set(),staleActions=new Set(),deferredActions=new Map();
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
 let metrics={age:34,height_cm:181,weight_kg:82,...shared.metrics};
 let profileRaw={goal:'general',...shared.profileRaw};
 let history=[{id:8,date:'23.10.2026',title:'Силовая'}];
 const client={
  root,handlers,fields,requests,scrollMoves,viewportHandlers,
  failOnce(action){failActions.add(action)},
  staleOnce(action){staleActions.add(action)},
  deferOnce(action){let release;deferredActions.set(action,new Promise(resolve=>{release=resolve}));return release},
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
   if(deferredActions.has(p.action)){const waiting=deferredActions.get(p.action);deferredActions.delete(p.action);await waiting}
   if(failActions.delete(p.action))return {ok:false,status:503,async json(){return {ok:false,error:'Временная ошибка API'}}};
   if(staleActions.delete(p.action)){
    workout={...workout,done:1,rest_remaining_seconds:shared.staleRestRemaining||0,current:{...workout.current,set_no:workout.current.set_no+1}};
    shared.workout=workout;
    return {ok:false,status:400,async json(){return {ok:false,error:'Этот подход уже изменился. Обнови тренировку'}}};
   }
   let response;
   const state=()=>({
    agreed:true,profile_raw:{...profileRaw},needs_health_profile:false,error:null,
    profile:{goal:'Поддерживать форму'},metrics:{...metrics},tier_name:'Тестовый доступ',tier:shared.tier||'start',food_catalog_available:shared.foodCatalogAvailable===true,fatsecret_diary_configured:shared.fatsecretReady===true,
    workout,history,birthday:shared.birthday||null,
    food_allergies:shared.foodAllergies||{available:false,choice:'unknown',items:[],recommendations_allowed:false},ai_personalization:shared.aiPermissions||{profile:false,health:false,cycle:false},
    plan_names:['Ноги и пресс'],next_day:'A',cycle_start:'2026-10-19',
    plan:[[{name:'Жим ногами',sets:3,low:10,high:12}]],
    calendar:[{id:2,week:1,day:'A',title:'Ноги и пресс',date:'2026-10-23',date_ru:'23.10.2026',status:'planned'}],
    stats:{total:1,sets:6}});
   if(p.action==='state')response={ok:true,data:state()};
   else if(p.action==='start'){
    assert.ok(['normal','tired'].includes(p.mood));
    workout={id:9,done:0,total:2,finished:false,title:'Ноги и пресс',current:{name:'Жим ногами',key:'leg_press',position:0,set_no:1,set_count:2,low:10,high:12,unit:'reps',rest_seconds:90,tip:'Двигай плавно',steps:['Настрой сиденье','Не блокируй колени'],start_position:'Сядь в тренажёр',muscles:'Бедра и ягодицы',mistakes:'Не блокируй колени',image_url:'https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/Leg_Press/0.jpg',image_credit:'Everkinetic · Free Exercise DB',image_license_url:'https://creativecommons.org/licenses/by-sa/4.0/'}};
    shared.workout=workout;
    response={ok:true,patch:{workout}};
   }else if(p.action==='record'){
    workout={...workout,done:1,rest_remaining_seconds:89,current:{...workout.current,set_no:2}};
    shared.workout=workout;
    response={ok:true,patch:{workout}};
   }else if(p.action==='food_history')response={ok:true,date:p.date,meals:shared.foodMeals||[],nutrients_available:false};
   else if(p.action==='ai_personalized_guidance')response={ok:true,advice:'Совет по реальному дневнику питания',used_ai:true};
   else if(p.action==='food_parse')response={ok:true,items:[{name:'овсянка',grams:70},{name:'творог 5%',grams:200}],unparsed:[]};
   else if(p.action==='garmin_day'){
    response={ok:true,date:p.date,connected:!!shared.garminConnected,
     last_sync_at:shared.garminConnected?'2026-10-25T09:00:00Z':null,
     dailies:shared.garminConnected?[{date_basis:'provider',
       values:{steps:7600,resting_heart_rate_bpm:57,active_calories_kcal:340,
         total_daily_calories_kcal:2260,body_battery_charged:42}}]:[],
     sleeps:shared.garminConnected?[{date_basis:'provider',
       values:{duration_minutes:420,sleep_score:81}}]:[],
     activities:shared.garminConnected?[{date_basis:'profile_timezone',
       values:{activity_type:'running',duration_seconds:1800,active_calories_kcal:215}}]:[]};
   }
   else if(p.action==='garmin_disconnect'){
    shared.garminConnected=false;response={ok:true,connected:false};
   }
   else if(p.action==='food_allergy_save'){
    assert.equal(p.consent,true);assert.equal(p.consent_version,'test-allergy-consent-v1');
    assert.ok(['declared','none'].includes(p.choice));
    shared.foodAllergies={available:true,choice:p.choice,
      items:p.choice==='declared'?p.items:[],recommendations_allowed:true,
      consent_version:'test-allergy-consent-v1'};
    response={ok:true,food_allergies:shared.foodAllergies};
   }
   else if(p.action==='food_allergy_revoke'){
    shared.foodAllergies={available:true,choice:'unknown',items:[],
       recommendations_allowed:false,consent_version:'test-allergy-consent-v1'};
    response={ok:true,food_allergies:shared.foodAllergies};
   }
   else if(p.action==='integrations_status'){
    response={ok:true,fatsecret:{available:!!shared.fatsecretReady,
     connected:!!shared.fatsecretConnected,last_sync_at:shared.fatsecretConnected?'2026-10-24T09:00:00Z':null},
     garmin:{available:false,connected:!!shared.garminConnected,
      last_sync_at:shared.garminConnected?'2026-10-25T09:00:00Z':null}};
   }
   else if(p.action==='fatsecret_account_status')
    response={ok:true,available:!!shared.fatsecretReady,
      connected:!!shared.fatsecretConnected,last_sync_at:null};
   else if(p.action==='fatsecret_account_connect'){
    shared.fatsecretConnected=false;
    response={ok:true,authorization_url:
     'https://authentication.fatsecret.com/oauth/authorize?oauth_token=TESTONLY',
     expires_minutes:10};
   }else if(p.action==='fatsecret_account_disconnect'){
    shared.fatsecretConnected=false;response={ok:true,connected:false};
   }else if(p.action==='fatsecret_diary_day'){
    assert.equal(p.date,shared.expectedFatsecretDate||'2026-10-25');
    const own=shared.fatsecretOverride||{};
    response={ok:true,date:p.date,complete:true,source:'fatsecret',
      totals:{calories_kcal:370,protein_g:32,fat_g:9,carbs_g:36},
      entries:[{external_id:'17',meal:own.meal||'Breakfast',name:own.name||'Овсянка',
        imported:!!shared.fatsecretImported,user_edited:!!(own.meal||own.name),
        user_name_override:own.name||null,user_meal_override:own.meal||null,
        kcal:200,protein:7,fat:4,carbs:32}]};
   }else if(p.action==='fatsecret_diary_import'){
    assert.equal(p.date,'2026-10-25');assert.deepEqual(Array.from(p.expected_ids),['17']);shared.fatsecretImported=true;
    response={ok:true,date:p.date,imported_ids:['17'],imported_count:1};
   }else if(p.action==='fatsecret_diary_import_edit'){
    assert.equal(p.external_id,'17');
    shared.fatsecretOverride={name:p.name_override,meal:p.meal_override};
    response={ok:true,date:p.date,external_id:p.external_id,imported:true};
   }else if(p.action==='fatsecret_diary_import_unlink'){
    assert.equal(p.external_id,'17');shared.fatsecretImported=false;
    shared.fatsecretOverride=null;
    response={ok:true,date:p.date,external_id:p.external_id,imported:false};
   }
   else if(p.action==='food_nutrition_day'){
    const entries=(shared.foodMeals||[]).flatMap(m=>m.items||[]);
    const registered=entries.filter(x=>x.nutrition_source==='fatsecret');
    const full=!!entries.length&&registered.length===entries.length;
    const kcal=registered.length*266;
    response={ok:true,source:'fatsecret',date:p.date,total_items:entries.length,
      resolved_items:registered.length,complete:full,partial:!full,
      totals:full?{kcal,protein_g:9.1*registered.length,fat_g:4.9*registered.length,carbs_g:46.9*registered.length}:null,
      known_subtotal:registered.length?{kcal,protein_g:9.1*registered.length,fat_g:4.9*registered.length,carbs_g:46.9*registered.length}:null,
      meals:(shared.foodMeals||[]).map(m=>({type:m.type,total_items:m.items.length,
       resolved_items:m.items.filter(i=>i.nutrition_source==='fatsecret').length,
       complete:m.items.every(i=>i.nutrition_source==='fatsecret'),
       known_subtotal:m.items.some(i=>i.nutrition_source==='fatsecret')?
          {kcal,protein_g:9.1,fat_g:4.9,carbs_g:46.9}:null})),
      items:entries.map(x=>({id:x.id,source:x.nutrition_source||null,
        nutrition:x.nutrition_source?{kcal:266,protein_g:9.1,fat_g:4.9,carbs_g:46.9}:null}))};
   }
   else if(p.action==='food_catalog_lookup')response={ok:true,source:'fatsecret',candidates:[{food_id:'42',name:'Овсянка сухая',servings:[{
     serving_id:'13',description:'100 г',grams:100,per_serving:{kcal:380,protein_g:13,fat_g:7,carbs_g:67}
   }]}]};
   else if(p.action==='food_catalog_attach'){
    assert.equal(p.food_id,'42');assert.equal(p.serving_id,'13');
    for(const m of shared.foodMeals||[])for(const i of m.items||[])if(i.id===p.id)i.nutrition_source='fatsecret';
    response={ok:true,item_id:p.id,source:'fatsecret',nutrients:{kcal:266,protein_g:9.1,fat_g:4.9,carbs_g:46.9}};
   }
   else if(p.action==='food_add'){
    shared.foodMeals=[...(shared.foodMeals||[]),{id:83,type:p.meal_type,items:p.items.map((v,i)=>({id:100+i,...v}))}];
    response={ok:true,date:p.date,meals:shared.foodMeals,nutrients_available:false};
   }else if(p.action==='food_update'){
    for(const meal of shared.foodMeals||[])for(const item of meal.items)if(item.id===p.id){item.name=p.name;item.grams=p.grams}
    response={ok:true,date:p.date,meals:shared.foodMeals||[]};
   }else if(p.action==='food_delete'){
    for(const meal of shared.foodMeals||[])meal.items=meal.items.filter(x=>x.id!==p.id);
    response={ok:true,date:p.date,meals:shared.foodMeals||[]};
   }else if(p.action==='training_preview'){
    response={ok:true,preview:{id:p.id,week:1,day:'A',date:'2026-10-23',name:'Ноги и пресс',
      duration_minutes:45,warmup_minutes:5,cooldown_minutes:3,cardio_note:'По программе',
      can_start:true,exercises:[{name:'Жим ногами',key:'leg_press',sets:3,low:10,high:12,unit:'reps',
      weight_kg:60,muscles:'Ноги',steps:['Настрой тренажёр','Двигай платформу плавно'],
      mistakes:'Не блокируй колени',start_position:'Сядь в тренажёр',substitutions:[],
      image_url:'https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/Leg_Press/0.jpg',image_credit:'Everkinetic · Free Exercise DB',image_license_url:'https://creativecommons.org/licenses/by-sa/4.0/'},
      {name:'Приседания к стулу',key:'chair_squat',sets:2,low:8,high:10,unit:'reps',
       weight_kg:null,steps:['Коснись стула','Встань плавно'],start_position:'Встань перед стулом',
       mistakes:'Не падай на стул',image_url:null,image_credit:null,image_license_url:null,substitutions:[]}]}};
   }else if(p.action==='progress_series')response={ok:true,exercises:shared.progressSeries||[]};
   else if(p.action==='body_weight_history')response={ok:true,measurements:[]};
   else if(p.action==='history_month')response={ok:true,dates:['2026-10-23'],month:p.month};
   else if(p.action==='history_page')response={ok:true,history:history.filter(x=>!p.date||x.date.split('.').reverse().join('-')===p.date),next_offset:null};
   else if(p.action==='detail')response={ok:true,detail:{title:'Силовая',date:'23.10.2026',items:[{name:'Жим ногами',result:'12 повт. · 60 кг'}]}};
   else if(p.action==='cardio'){assert.equal(p.type,'Велосипед');if(shared.trackHistory)history=[{id:81,date:'23.10.2026',title:'Кардио · Велосипед'},...history];response={ok:true,data:state()};}
   else if(p.action==='feedback')response={ok:true,saved:true,message:'Отзыв сохранён'};
   else if(p.action==='health_analyze'){
     assert.equal(p.adult,true);assert.equal(p.privacy_ack,true);assert.equal(p.ai_consent,true,'No Yandex health request without opt-in');
     response={ok:true,analysis:{affected:['knee'],pain_score:3,symptom_course:'stable',danger_signs:false,short_summary:'Беспокоит колено'}};
    }
    else if(p.action==='onboarding'){
     assert.equal(p.terms,true);assert.equal(p.privacy,true);assert.equal(p.health,true);
     assert.equal(p.answers.age_group,'adult');
     assert.ok(p.metrics.age>=18);
     assert.ok(Array.isArray(p.health_profile.affected));
     assert.equal(p.answers.weekdays.length,Number(p.answers.days));
     assert.equal(new Set(p.answers.weekdays).size,p.answers.weekdays.length);
     profileRaw={...p.answers};Object.assign(metrics,p.metrics);
     response={ok:true,data:state()};
    }
    else if(p.action==='save_metrics'){
    assert.ok(Object.keys(p.metrics).every(k=>['age','birth_date','height_cm','weight_kg'].includes(k)));
    Object.assign(metrics,p.metrics);response={ok:true,patch:{metrics:{...metrics},zones:[]}};
   }
   else if(p.action==='finish'){workout=null;shared.workout=null;response={ok:true,data:state()}}
   else if(p.action==='skip')response={ok:true,patch:{workout}};
   else throw Error('Unexpected action: '+p.action);
   return {ok:true,status:200,async json(){return response}};
  }
 };
 const fixtureNow=shared.now||'2026-10-25T12:00:00Z';
 const ClientDate=class extends Date{constructor(...args){super(...(args.length?args:[fixtureNow]))}static now(){return new Date(fixtureNow).getTime()}};
 const context={
  document:doc,
  window:{Telegram:{WebApp:{initData:auth?'signed-for-test':'',ready(){},expand(){shared.expandCalls=(shared.expandCalls||0)+1},...(shared.fullscreen?{isVersionAtLeast(){return !shared.oldTelegram},requestFullscreen(){shared.fullscreenCalls=(shared.fullscreenCalls||0)+1;if(shared.fullscreenThrows)throw Error('Fullscreen unavailable')},onEvent(){}}:{})}},scrollTo(){},scrollBy(data){scrollMoves.push(data.top)},visualViewport:{offsetTop:0,addEventListener(n,fn){viewportHandlers[n]=fn}},sessionStorage:{getItem(k){return temporary.get(k)||null},setItem(k,v){temporary.set(k,v)},removeItem(k){temporary.delete(k)}}},
  fetch:client.fetch,
  setTimeout(fn){return 1},clearTimeout(){},setInterval(fn){return 1},
  AbortController,Date:ClientDate,Set,Number,String,Array,Map,Object,RegExp,Math,FormData:FakeFormData,
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
 // Existing user: questionnaire is never silently interpreted as "no allergy".
 const allergy=createClient(true,{foodAllergies:{available:true,choice:'unknown',
    items:[],recommendations_allowed:false,consent_version:'test-allergy-consent-v1'}});
 await settle();await allergy.click({nav:'food'});await settle();
 assert.match(allergy.root.innerHTML,/Ответить в профиле/);
 await allergy.click({nav:'profile'});await settle();
 assert.match(allergy.root.innerHTML,/Есть ли у вас аллергия/);
 await allergy.click({onboardPick:'foodChoice',value:'declared'});
 allergy.handlers.input({target:{dataset:{onboard:'foodInput'},type:'text',value:'Яйца, Арахис'}});
 await allergy.click({cmd:'food-allergy-add'});
 assert.match(allergy.root.innerHTML,/Яйца/);
 assert.match(allergy.root.innerHTML,/Арахис/);
 allergy.handlers.change({target:{dataset:{onboard:'foodConsent'},type:'checkbox',checked:true}});
 await allergy.click({cmd:'food-allergy-save'});
 const writes=allergy.requests.filter(x=>x.action==='food_allergy_save');
 assert.equal(writes.length,1);
 assert.deepEqual(writes[0].items.map(x=>x.name),['Яйца','Арахис']);
 assert.ok(writes[0].items.every(x=>x.kind==='allergy'));
 assert.match(allergy.root.innerHTML,/Пищевые ограничения сохранены/);
 // Editable allergen type updates are sent only after explicit save.
 allergy.handlers.change({target:{dataset:{foodAllergyKind:'0'},value:'intolerance'}});
 await allergy.click({cmd:'food-allergy-save'});
 const changed=allergy.requests.filter(x=>x.action==='food_allergy_save');
 assert.equal(changed.length,2);
 assert.equal(changed[1].items[0].kind,'intolerance');
 // Revoke is a two-stage explicit confirmation, never immediate deletion.
 await allergy.click({cmd:'food-allergy-revoke'});
 assert.match(allergy.root.innerHTML,/Да, удалить/);
 assert.equal(allergy.requests.filter(x=>x.action==='food_allergy_revoke').length,0);
 await allergy.click({cmd:'food-allergy-revoke-cancel'});
 assert.equal(allergy.requests.filter(x=>x.action==='food_allergy_revoke').length,0);
 await allergy.click({cmd:'food-allergy-revoke'});
 await allergy.click({cmd:'food-allergy-revoke-confirm'});
 assert.equal(allergy.requests.filter(x=>x.action==='food_allergy_revoke').length,1);
 assert.match(allergy.root.innerHTML,/Согласие отозвано/);
 await allergy.click({nav:'food'});await settle();
 assert.match(allergy.root.innerHTML,/Ответить в профиле/);
 const legacy=createClient(true);
 await settle();await legacy.click({nav:'food'});await settle();
 assert.doesNotMatch(legacy.root.innerHTML,/Ответить в профиле/);

 const blocked=createClient(false);
 assert.match(blocked.root.innerHTML,/Открой из Telegram/);
 assert.equal(blocked.requests.length,0);
 for(const [instant,expected] of [
  ['2026-10-25T02:00:00Z','Доброй ночи!'],
  ['2026-10-25T08:00:00Z','Доброе утро!'],
  ['2026-10-25T14:00:00Z','Добрый день!'],
  ['2026-10-25T20:00:00Z','Добрый вечер!']
 ]){
  const local=createClient(true,{now:instant,metrics:{timezone:'UTC'}});await settle();
  assert.ok(local.root.innerHTML.includes(expected),'Greeting must follow saved timezone: '+instant);
  assert.match(local.root.innerHTML,/Воскресенье, 25 октября/,'Date is capitalized and localized');
  assert.match(local.root.innerHTML,/Сегодня день восстановления/,'No workout is scheduled today');
 }
 const severe=createClient(true,{metrics:{sex:'female'}});await settle();
 await severe.click({cmd:'mood'});
 assert.match(severe.root.innerHTML,/Сильная боль или слабость/);
 await severe.click({cmd:'start-severe'});
 assert.match(severe.root.innerHTML,/Тренировка не начата/,'Recovery choice must show its outcome');
 assert.equal(severe.requests.filter(x=>x.action==='start').length,0,
   'Severe pain must not start a session');
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
 const newerSet=createClient(true,{staleRestRemaining:50,workout:{id:72,done:1,total:4,finished:false,title:'Зал',rest_remaining_seconds:47,
  current:{name:'Жим ногами',position:0,set_no:2,set_count:4,low:10,high:12,unit:'reps',rest_seconds:90}}});
 await settle();await newerSet.click({cmd:'rest-skip'});
 newerSet.input('reps','12');newerSet.staleOnce('record');await newerSet.click({cmd:'record'});
 assert.match(newerSet.root.innerHTML,/rest-count/,'Skipping an earlier rest must not suppress rest after another client advances the set');
 const shared={storage:new Map()};
 const app=createClient(true,shared);
 await settle();
 assert.match(app.root.innerHTML,/Начать тренировку/);
 assert.ok(app.requests.find(x=>x.action==='state'));
 await app.click({cmd:'mood'});
 assert.match(app.root.innerHTML,/Самочувствие перед началом/);
 await app.click({cmd:'start-normal'});
 assert.match(app.root.innerHTML,/Жим ногами/);
 assert.equal((app.root.innerHTML.match(/class="nav-item /g)||[]).length,3,'Active sets retain three approved bottom tabs');
 assert.match(app.root.innerHTML,/id="reps"[^>]*value=""/);
 await app.click({cmd:'exercise-live'});
 assert.match(app.root.innerHTML,/fq-exercise-photo/,'Live card has vetted photo');
 assert.match(app.root.innerHTML,/CC BY-SA 4[.]0/,'Live card credits images');
 assert.match(app.root.innerHTML,/Не блокируй колени/,'Live card shows real cues');
 await app.click({cmd:'exercise-back'});
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
 assert.equal((app.root.innerHTML.match(/class="nav-item /g)||[]).length,3,'Rest screen keeps approved nav');
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
 assert.match(app.root.innerHTML,/class="surface cardio-inline"/,'Cardio stays embedded on workouts screen');
 assert.match(app.root.innerHTML,/id="cardio-min"[^>]*value=""/,'Successful save clears cardio duration');
 assert.match(app.root.innerHTML,/id="cardio-hr"[^>]*value=""/,'Successful save clears heart rate');
 await app.click({cmd:'cardio-add'});
 assert.match(app.root.innerHTML,/id="cardio-min"[^>]*value=""/);
 assert.match(app.root.innerHTML,/id="cardio-hr"[^>]*value=""/);
 await app.click({cmd:'close'});
 assert.equal((app.root.innerHTML.match(/class="nav-item /g)||[]).length,3,'Only three bottom nav buttons');
 assert.match(app.root.innerHTML,/Тренировочный план/,'Workouts contain the four-week plan');
 assert.ok(app.root.innerHTML.indexOf('id="cardio-entry"')<app.root.innerHTML.indexOf('id="training-plan"'),'Plan follows additional training');
 assert.match(app.root.innerHTML,/Начать тренировку/,'Workout start remains on Today');
 await app.click({nav:'progress'});
 await settle();
 assert.ok(app.requests.some(x=>x.action==='progress_series'),'Progress loads owner-scoped history separately');
 const progressHtml=app.root.innerHTML;
 assert.doesNotMatch(progressHtml,/id="training-plan"/,'Progress shows history, not training plan');
 assert.doesNotMatch(progressHtml,/Garmin Connect|Женский календарь/);
 assert.equal((app.requests.filter(x=>x.action==='progress_series')).length>=1,true);
 const garminClient=createClient(true,{garminConnected:true,
   now:'2026-10-25T12:00:00Z',metrics:{timezone:'UTC'}});
 await settle();await garminClient.click({nav:'profile'});await settle();
 assert.match(garminClient.root.innerHTML,/Garmin Connect/);
 assert.match(garminClient.root.innerHTML,/Последняя успешная синхронизация/);
 assert.doesNotMatch(garminClient.root.innerHTML,/data-cmd="garmin-connect"/,'Garmin OAuth does not exist');
 await garminClient.click({nav:'progress'});await settle();
 assert.ok(garminClient.requests.some(x=>x.action==='garmin_day'&&x.date==='2026-10-25'));
 assert.match(garminClient.root.innerHTML,/Garmin Connect/);
 assert.match(garminClient.root.innerHTML,/Последняя синхронизация/);
 assert.match(garminClient.root.innerHTML,/7600/,'Only observed Garmin steps');
 assert.match(garminClient.root.innerHTML,/2260.*ккал/,'Total day energy shown separately');
 assert.match(garminClient.root.innerHTML,/340.*ккал/,'Active calories remain distinct');
 assert.match(garminClient.root.innerHTML,/215.*ккал активности/,'Activity calories not added to all-day totals');
 assert.match(garminClient.root.innerHTML,/Сон/);
 assert.match(garminClient.root.innerHTML,/42/);
 await garminClient.click({cmd:'garmin-refresh'});await settle();
 assert.ok(garminClient.requests.filter(x=>x.action==='garmin_day').length>=2);
 await garminClient.click({cmd:'garmin-disconnect-open'});
 assert.match(garminClient.root.innerHTML,/Отключить Garmin/);
 await garminClient.click({cmd:'garmin-disconnect-confirm'});await settle();
 assert.ok(garminClient.requests.some(x=>x.action==='garmin_disconnect'));
 assert.doesNotMatch(garminClient.root.innerHTML,/Garmin Connect/,'Revoked Garmin never renders stale private metrics');

 assert.doesNotMatch(progressHtml,/19\.10\.2026 — 25\.10\.2026/,'Progress no longer includes plan dates');
 await app.click({nav:'home'});
 await app.click({cmd:'week',week:'1'});
 assert.match(app.root.innerHTML,/23\.10\.2026/,'Expanded week contains owner calendar session');
 assert.match(app.root.innerHTML,/data-cmd="training-preview"/,'Every scheduled workout opens read-only preview');
 await app.click({cmd:'training-preview',id:'2'});await settle();
 await app.click({cmd:'exercise-card',index:'0'});
 assert.match(app.root.innerHTML,/fq-exercise-photo/,'A matching photo appears in Mini App');
 assert.match(app.root.innerHTML,/CC BY-SA 4[.]0/,'Source and license visible');
 assert.match(app.root.innerHTML,/Настрой тренажёр/,'Specific motion cue shown');
 await app.click({cmd:'exercise-back'});
 await app.click({cmd:'exercise-card',index:'1'});
 assert.doesNotMatch(app.root.innerHTML,/<img src=/,'Do not show Smith squat for chair squat');
 assert.match(app.root.innerHTML,/Подтверждённого изображения/);
 await app.click({cmd:'exercise-back'});
 await app.click({cmd:'close'});
 await app.click({cmd:'week',week:'1'});
 assert.doesNotMatch(app.root.innerHTML,/class="week-details"/,'Week button collapses details');

 await app.click({nav:'profile'});
 assert.match(app.root.innerHTML,/Профиль:/,'Existing profile is an editable questionnaire');
 assert.match(app.root.innerHTML,/data-onboard="birth_date"/);
 assert.doesNotMatch(app.root.innerHTML,/data-onboard="age"/,'Birth date replaces age input');
 assert.match(app.root.innerHTML,/Ранее сохранён только возраст/);
 assert.match(app.root.innerHTML,/birthday_telegram_consent/);
 assert.match(app.root.innerHTML,/data-onboard="weight_kg"/);
 assert.doesNotMatch(app.root.innerHTML,/data-onboard="timezone"|Подтверждаю выбранный часовой пояс|Мне исполнилось 18 лет/);
 assert.match(app.root.innerHTML,/Сохранить изменения/);
 assert.match(app.root.innerHTML,/Бесплатно/);
 assert.match(app.root.innerHTML,/1 000 ₽\/мес\./);
 assert.match(app.root.innerHTML,/data-cmd="tier-select" data-tier="max"/);
 assert.doesNotMatch(app.root.innerHTML,/Редактировать анкету|Изменить параметры/);
 assert.doesNotMatch(app.root.innerHTML,/data-cmd="profile-metrics-edit"/);
 await app.click({nav:'home'});
 assert.match(app.root.innerHTML,/Доброе|Добрый|Доброй/);
 const birthday=createClient(true,{now:'2026-10-26T08:00:00Z',profileRaw:{weekdays:[0,2,4]},metrics:{timezone:'UTC',sex:'male',birth_date:'1992-10-26'},
   birthday:{show_congratulations:true,discount_percent:10,coach_price_rub:900}});
 await settle();assert.match(birthday.root.innerHTML,/С днём рождения/);
 assert.match(birthday.root.innerHTML,/900 ₽ вместо 1 000 ₽/);
 await birthday.click({nav:'profile'});
 assert.match(birthday.root.innerHTML,/data-onboard="birth_date"/);
 assert.match(birthday.root.innerHTML,/value="1992-10-26"/);
 birthday.handlers.change({target:{dataset:{onboard:'birth_date'},type:'date',value:'1992-10-25'}});
 birthday.handlers.change({target:{dataset:{onboard:'birthday_telegram_consent'},type:'checkbox',checked:true}});
 await birthday.click({cmd:'onboard-save'});
 assert.equal(birthday.requests.filter(x=>x.action==='onboarding')[0].metrics.birth_date,'1992-10-25');
 assert.equal(birthday.requests.filter(x=>x.action==='onboarding')[0].birthday_telegram_consent,true);
 assert.match(app.root.innerHTML,/Отзывы и предложения/);
 await app.click({cmd:'feedback-open'});
 assert.match(app.root.innerHTML,/id="feedback-text"/);
 await app.click({cmd:'feedback-send'});
 assert.equal(app.requests.filter(x=>x.action==='feedback').length,0,'Invalid feedback not submitted');
 app.input('feedback-text','Очень полезное приложение');
 await app.click({cmd:'feedback-send'});
 assert.ok(app.requests.some(x=>x.action==='feedback'),'Feedback calls signed API');
 assert.match(app.root.innerHTML,/Отзыв сохранён/);
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
 assert.match(app.root.innerHTML,/class="fq-live-dialog history-modal"/,'History uses approved bottom sheet');
 assert.match(app.root.innerHTML,/role="region" aria-label="Список сохранённых занятий"/);
 assert.match(app.root.innerHTML,/Закрыть историю/);
 await app.click({cmd:'detail',id:'8'});
 assert.ok(app.requests.some(x=>x.action==='detail'&&x.id===8));
 assert.match(app.root.innerHTML,/12 повт/);
 await app.click({nav:'food'});await settle();
 assert.match(app.root.innerHTML,/id="food-text"/,'Manual products can be recorded without Yandex AI');
 assert.match(app.root.innerHTML,/Для продуктов, которые готовятся/);
 assert.doesNotMatch(app.root.innerHTML,/nutrition-consent/,'No duplicate Yandex consent in nutrition');
 assert.doesNotMatch(app.root.innerHTML,/id="nutrition-file"/,'Optional AI upload hidden without stored consent');
 app.handlers.input({target:{id:'food-text',value:'овсянка 70 грамм, творог 5% 200 грамм'}});
 await app.click({cmd:'food-parse'});
 assert.match(app.root.innerHTML,/Проверь перед сохранением/);
 await app.click({cmd:'food-save'});
 assert.match(app.root.innerHTML,/овсянка/,'Confirmed meal is visible after save');
 assert.ok(app.requests.some(x=>x.action==='food_add'&&x.items.length===2),'Real product weights submitted to server');
 const first=app.requests.find(x=>x.action==='food_add');
 assert.equal(first.items[0].grams,70);
 await app.click({cmd:'food-edit',id:'100'});
 app.fields.set('food-edit-name',{id:'food-edit-name',value:'овсянка сухая'});
 app.fields.set('food-edit-grams',{id:'food-edit-grams',value:'75'});
 await app.click({cmd:'food-edit-save'});
 assert.ok(app.requests.some(x=>x.action==='food_update'&&x.grams==='75'));
 await app.click({cmd:'food-delete',id:'100'});
 await app.click({cmd:'food-delete-confirm'});
 assert.ok(app.requests.some(x=>x.action==='food_delete'&&x.id===100));
 const catalogClient=createClient(true,{foodCatalogAvailable:true,
  foodMeals:[{id:81,type:'breakfast',items:[{id:202,name:'овсянка сухая',grams:70}]}]});
 await settle();await catalogClient.click({nav:'food'});await settle();
 await catalogClient.click({cmd:'food-edit',id:'202'});
 assert.match(catalogClient.root.innerHTML,/Найти в FatSecret/,'Official catalogue only when configured');
 await catalogClient.click({cmd:'food-catalog-open'});
 catalogClient.fields.set('food-catalog-query',{id:'food-catalog-query',value:'овсянка'});
 await catalogClient.click({cmd:'food-catalog-search'});
 assert.ok(catalogClient.requests.some(x=>x.action==='food_catalog_lookup'&&x.query==='овсянка'));
 assert.match(catalogClient.root.innerHTML,/Овсянка сухая/);
 await catalogClient.click({cmd:'food-catalog-link',foodId:'42',servingId:'13'});
 assert.ok(catalogClient.requests.some(x=>x.action==='food_catalog_attach'&&x.id===202));
 await settle();
 assert.ok(catalogClient.requests.some(x=>x.action==='food_nutrition_day'),
  'Daily macros must load automatically after provider verification');
 assert.match(catalogClient.root.innerHTML,/266.*ккал/,'Only verified serving may produce KБЖУ');
 await catalogClient.click({cmd:'food-nutrition-day'});
 assert.ok(catalogClient.requests.some(x=>x.action==='food_nutrition_day'));
 assert.match(catalogClient.root.innerHTML,/КБЖУ за день/,'Full day sum only for completely verified day');
 assert.match(catalogClient.root.innerHTML,/266.*ккал/);
 const mixedClient=createClient(true,{foodCatalogAvailable:true,
  foodMeals:[{id:84,type:'breakfast',items:[
    {id:202,name:'Овсянка сухая',grams:70,nutrition_source:'fatsecret'},
    {id:203,name:'Банан без базы',grams:120}]}]});
 await settle();await mixedClient.click({nav:'food'});await settle();
 assert.ok(mixedClient.requests.some(x=>x.action==='food_nutrition_day'),
  'Existing verified food macros load without an extra user action');
 await mixedClient.click({cmd:'food-nutrition-day'});
 assert.match(mixedClient.root.innerHTML,/Данные за день неполные/);
 assert.match(mixedClient.root.innerHTML,/1 из 2 продуктов/);
 assert.doesNotMatch(mixedClient.root.innerHTML,/КБЖУ за день:/,'Partial sum is never full day total');
 const unconfigured=createClient(true,{foodCatalogAvailable:false});
 await settle();await unconfigured.click({nav:'food'});await settle();
 assert.doesNotMatch(unconfigured.root.innerHTML,/Рассчитать КБЖУ за день/);

 const noOAuth=createClient(true,{fatsecretReady:false});
 await settle();await noOAuth.click({nav:'food'});await settle();
 assert.doesNotMatch(noOAuth.root.innerHTML,/Подключить FatSecret/);
 await noOAuth.click({nav:'profile'});await settle();
 assert.match(noOAuth.root.innerHTML,/Временно недоступен/);
 assert.doesNotMatch(noOAuth.root.innerHTML,/data-cmd="fatsecret-connect"/);
 assert.ok(!noOAuth.requests.some(x=>x.action==='fatsecret_account_connect'));
 const oauthClient=createClient(true,{fatsecretReady:true,fatsecretConnected:false});
 await settle();await oauthClient.click({nav:'profile'});await settle();
 assert.match(oauthClient.root.innerHTML,/Подключения/);
 assert.match(oauthClient.root.innerHTML,/Не подключён/);
 assert.match(oauthClient.root.innerHTML,/Временно недоступен/,'Garmin must not offer fake authorization');
 assert.match(oauthClient.root.innerHTML,/data-cmd="fatsecret-connect"/);
 await oauthClient.click({cmd:'fatsecret-connect'});
 assert.ok(oauthClient.requests.some(x=>x.action==='fatsecret_account_connect'));
 assert.match(oauthClient.root.innerHTML,/authentication.fatsecret.com\/oauth\/authorize/);
 const linkedClient=createClient(true,{fatsecretReady:true,fatsecretConnected:true,now:'2026-10-25T12:00:00Z',metrics:{timezone:'UTC'}});
 await settle();await linkedClient.click({nav:'food'});await settle();
 assert.match(linkedClient.root.innerHTML,/Аккаунт подключён/);
 await linkedClient.click({cmd:'fatsecret-diary-day'});
 assert.ok(linkedClient.requests.some(x=>x.action==='fatsecret_diary_day'));
 assert.match(linkedClient.root.innerHTML,/370.*ккал/);
 assert.match(linkedClient.root.innerHTML,/Овсянка/);
 await linkedClient.click({cmd:'fatsecret-import-day'});
 assert.match(linkedClient.root.innerHTML,/Подтвердить импорт/);
 assert.equal(linkedClient.requests.filter(x=>x.action==='fatsecret_diary_import').length,0,
  'Preview must not persist before explicit confirmation');
 await linkedClient.click({cmd:'fatsecret-import-confirm'});
 assert.ok(linkedClient.requests.some(x=>x.action==='fatsecret_diary_import'));
 assert.match(linkedClient.root.innerHTML,/Импортировано в FORMIQ/);
 await linkedClient.click({cmd:'fatsecret-entry-edit',id:'17'});
 assert.match(linkedClient.root.innerHTML,/Исправление импортированной записи/);
 linkedClient.fields.set('fatsecret-override-name',{id:'fatsecret-override-name',value:'Моя овсянка'});
 linkedClient.fields.set('fatsecret-override-meal',{id:'fatsecret-override-meal',value:'snack'});
 await linkedClient.click({cmd:'fatsecret-entry-save'});
 assert.ok(linkedClient.requests.some(x=>x.action==='fatsecret_diary_import_edit'&&x.name_override==='Моя овсянка'));
 assert.match(linkedClient.root.innerHTML,/Моя овсянка/);
 await linkedClient.click({cmd:'fatsecret-import-day'});
 assert.match(linkedClient.root.innerHTML,/уже импортировано/);
 await linkedClient.click({cmd:'fatsecret-import-confirm'});
 assert.match(linkedClient.root.innerHTML,/Импортировано в FORMIQ/);
 await linkedClient.click({cmd:'fatsecret-entry-unlink',id:'17'});
 assert.ok(linkedClient.requests.some(x=>x.action==='fatsecret_diary_import_unlink'));
 assert.doesNotMatch(linkedClient.root.innerHTML,/Импортировано в FORMIQ/);
 await linkedClient.click({nav:'profile'});await settle();
 assert.match(linkedClient.root.innerHTML,/Подключения/);
 assert.match(linkedClient.root.innerHTML,/Последняя успешная синхронизация/);
 await linkedClient.click({cmd:'fatsecret-disconnect-open'});
 assert.match(linkedClient.root.innerHTML,/Отключить FatSecret\?/);
 await linkedClient.click({cmd:'fatsecret-disconnect-confirm'});
 assert.ok(linkedClient.requests.some(x=>x.action==='fatsecret_account_disconnect'));
 assert.match(linkedClient.root.innerHTML,/Не подключён/);
 assert.match(linkedClient.root.innerHTML,/data-cmd="fatsecret-connect"/);
 const ownerCoach=createClient(true,{tier:'max',now:'2026-10-25T12:00:00Z',metrics:{timezone:'UTC'},
    aiPermissions:{profile:true,health:true,cycle:false}});
  await settle();
  assert.doesNotMatch(ownerCoach.root.innerHTML,/Персональный совет Yandex AI/,
    'Trainer AI should expose a recommendation below the four-week plan');
  await ownerCoach.click({cmd:'ai-tip-training'});await settle();
  assert.ok(ownerCoach.requests.some(x=>x.action==='ai_personalized_guidance'&&
    x.purpose==='training'));
  await ownerCoach.click({nav:'food'});await settle();
  assert.doesNotMatch(ownerCoach.root.innerHTML,/Совет Yandex AI по рациону/);
  await ownerCoach.click({cmd:'ai-tip-nutrition'});await settle();
  assert.ok(ownerCoach.requests.some(x=>x.action==='ai_personalized_guidance'&&
    x.purpose==='nutrition'&&x.date==='2026-10-25'));
  assert.doesNotMatch(ownerCoach.root.innerHTML,/Совет по реальному дневнику питания/);
  await ownerCoach.click({cmd:'food-parse'});await settle();
  await ownerCoach.click({cmd:'food-save'});await settle();
  assert.doesNotMatch(ownerCoach.root.innerHTML,/Совет по реальному дневнику питания/,
    'Editing the diary invalidates previous AI nutrition guidance');
  const delayedAdviceClient=createClient(true,{tier:'max',
    now:'2026-10-25T12:00:00Z',metrics:{timezone:'UTC'},
    aiPermissions:{profile:true,health:true,cycle:false}});
  await settle();await delayedAdviceClient.click({nav:'food'});await settle();
  const releaseAdvice=delayedAdviceClient.deferOnce('ai_personalized_guidance');
  const pendingAdvice=delayedAdviceClient.click({cmd:'ai-tip-nutrition'});await settle();
  assert.ok(delayedAdviceClient.requests.some(x=>x.action==='ai_personalized_guidance'),
      'AI request begins against existing food data');
  await delayedAdviceClient.click({cmd:'food-parse'});await settle();
  await delayedAdviceClient.click({cmd:'food-save'});await settle();
  releaseAdvice();await pendingAdvice;await settle();
  assert.doesNotMatch(delayedAdviceClient.root.innerHTML,/Совет по реальному дневнику питания/,
      'A delayed AI response must not appear after editing the same-day diary');
  const diaryOnly=createClient(true,{tier:'start',
    aiPermissions:{profile:true,health:true,cycle:false}});
  await settle();await diaryOnly.click({nav:'food'});await settle();
  assert.doesNotMatch(diaryOnly.root.innerHTML,/Совет Yandex AI по рациону/,
    'Diary tier never exposes paid Yandex coaching');
  assert.doesNotMatch(diaryOnly.root.innerHTML,/id="nutrition-file"/,
    'Diary tier must not advertise AI report upload');
  const reportClient=createClient(true,{tier:'max',
  aiPermissions:{profile:true,health:true,cycle:false}});
 await settle();await reportClient.click({nav:'food'});await settle();
 assert.match(reportClient.root.innerHTML,/nutrition-file/);
 assert.doesNotMatch(reportClient.root.innerHTML,/nutrition-consent/);
 reportClient.fields.set('nutrition-error',{id:'nutrition-error',textContent:''});
 await reportClient.click({cmd:'nutrition-analyze'});
 assert.match(reportClient.fields.get('nutrition-error').textContent,/Выбери/);
 reportClient.fields.set('nutrition-file',{id:'nutrition-file',files:[{name:'report.csv',size:500,type:'text/csv'}]});
 await reportClient.click({cmd:'nutrition-analyze'});
 assert.equal(reportClient.requests.filter(x=>x.action==='nutrition-report').length,1);
 assert.match(reportClient.root.innerHTML,/1900 ккал/);
 const weighted=createClient(true,{progressSeries:[{
  key:'leg_press',name:'Жим ногами',points:[
   {date:'2026-10-19',weight:55},{date:'2026-10-21',weight:60}
  ]}]});
 await settle();await weighted.click({nav:'progress'});await settle();
 assert.match(weighted.root.innerHTML,/fq-progress-chart/,'Only server-supplied values form the line');
 assert.match(weighted.root.innerHTML,/60 кг/);
 const polished={fullscreen:true};
  const ux=createClient(true,polished);await settle();
  assert.equal(polished.fullscreenCalls,1,'Supported Telegram clients request true fullscreen');
  assert.match(ux.root.innerHTML,/Тренировки/);
   assert.equal((ux.root.innerHTML.match(/class="nav-item /g)||[]).length,3,'Fullscreen has three bottom buttons');
  for(const fallback of [{fullscreen:true,oldTelegram:true},{fullscreen:true,fullscreenThrows:true}]){
   const legacyClient=createClient(true,fallback);await settle();
   assert.equal(fallback.expandCalls,1,'Fallback clients stay expanded');
   assert.equal(fallback.fullscreenCalls||0,fallback.oldTelegram?0:1);
   assert.match(legacyClient.root.innerHTML,/Начать тренировку/,'Fullscreen rejection must not prevent API startup');
  }
  for(const [now,timezone,expected] of [
   ['2026-11-01T00:30:00Z','America/Los_Angeles','2026-10'],
   ['2026-10-31T23:30:00Z','Asia/Tokyo','2026-11']
  ]){
   const localCalendar=createClient(true,{now,metrics:{timezone}});await settle();
   await localCalendar.click({nav:'progress'});await localCalendar.click({cmd:'calendar'});
   assert.equal(localCalendar.requests.find(x=>x.action==='history_month').month,expected,'Calendar starts in the saved user timezone');
  }
  assert.match(ux.root.innerHTML,/Тренировочный план/);
  assert.match(ux.root.innerHTML,/week-range/);
  await ux.click({nav:'progress'});
  assert.doesNotMatch(ux.root.innerHTML,/Тренировочный план/);
  await ux.click({nav:'profile'});
  
  assert.equal((ux.root.innerHTML.match(/data-onboard-weekday="[0-6]"/g)||[]).length,7);
  assert.match(ux.root.innerHTML,/Количество тренировок определяется автоматически/);
  assert.doesNotMatch(ux.root.innerHTML,/data-onboard="days"/,'No redundant count selector');
  assert.match(ux.root.innerHTML,/data-onboard="minutes"/,'Duration is a select');
  assert.doesNotMatch(ux.root.innerHTML,/id="onboard-duration"/,'No duration slider');
  assert.match(ux.root.innerHTML,/class="option-grid fq-sex-options"/,'Exactly two sex buttons');
  assert.equal((ux.root.innerHTML.match(/data-onboard-pick="sex"/g)||[]).length,2);
  assert.doesNotMatch(ux.root.innerHTML,/Не указывать/);
  assert.match(ux.root.innerHTML,/Какой спортивный инвентарь/);
  assert.doesNotMatch(ux.root.innerHTML,/href="\/mini\/legacy"/,'Editing stays in v5');
  await ux.click({cmd:'onboard-save'});
  assert.equal(ux.requests.filter(x=>x.action==='onboarding').length,0,'No consent, no save');
  for(const key of ['terms','privacy','health'])
    ux.handlers.change({target:{dataset:{onboard:key},type:'checkbox',checked:true}});
  await ux.click({cmd:'onboard-save'});
  assert.match(ux.root.innerHTML,/Выбери Мужской или Женский/);
  await ux.click({onboardWeekday:'0'});await ux.click({onboardWeekday:'3'});
  await ux.click({onboardPick:'sex',value:'female'});
  ux.handlers.change({target:{dataset:{onboard:'minutes'},type:'select-one',value:'120'}});
  ux.handlers.input({target:{dataset:{onboard:'equipment_description'},type:'textarea',value:'гантели, резинки'}});
  await ux.click({cmd:'onboard-save'});
  const edits=ux.requests.filter(x=>x.action==='onboarding');
  assert.equal(edits.length,1,'First-run saves directly using chosen weekdays. UI: '+ux.root.innerHTML.slice(0,500));
  assert.equal(edits[0].metrics.weight_kg,82);
  assert.equal(edits[0].metrics.sex,'female');
  assert.equal(edits[0].answers.minutes,'120');
  assert.deepEqual(Array.from(edits[0].answers.weekdays),[0,3]);
  assert.equal(edits[0].answers.days,'2');
  assert.equal(edits[0].equipment_description,'гантели, резинки');
  assert.match(ux.root.innerHTML,/Тренировки/,'Returns to main app after successful save');
  await ux.click({nav:'profile'});
  assert.match(ux.root.innerHTML,/data-onboard-weekday="0" aria-pressed="true"/);
  
  assert.match(ux.root.innerHTML,/data-onboard-weekday="0" aria-pressed="true"/);
  assert.match(ux.root.innerHTML,/data-onboard-weekday="3" aria-pressed="true"/);

  const sevenDays=createClient(true,{profileRaw:{days:'7',weekdays:[0,1,2,3,4,5,6]}});await settle();
  await sevenDays.click({nav:'profile'});
  assert.equal((sevenDays.root.innerHTML.match(/data-onboard-weekday="[0-6]" aria-pressed="true"/g)||[]).length,7);
  for(const key of ['terms','privacy','health'])sevenDays.handlers.change({target:{dataset:{onboard:key},type:'checkbox',checked:true}});
  await sevenDays.click({onboardPick:'sex',value:'male'});
  for(let day=1;day<7;day++)await sevenDays.click({onboardWeekday:String(day)});
  await sevenDays.click({cmd:'onboard-save'});
  assert.deepEqual(Array.from(sevenDays.requests.find(x=>x.action==='onboarding').answers.weekdays),[0]);
  assert.equal(sevenDays.requests.find(x=>x.action==='onboarding').answers.days,'1');

  const aiDenied=createClient(true,{storage:new Map()});await settle();
  await aiDenied.click({nav:'profile'});
  await aiDenied.click({onboardPick:'sex',value:'male'});
  aiDenied.handlers.change({target:{dataset:{onboard:'profileAiConsent'},type:'checkbox',checked:true}});
  await aiDenied.click({cmd:'onboard-ai'});
  assert.equal(aiDenied.requests.filter(x=>x.action==='health_analyze').length,0,'Unpersisted AI opt-in never transmits health text');

  const ai=createClient(true,{storage:new Map(),aiPermissions:{profile:true,health:true,cycle:false}});await settle();
  await ai.click({nav:'profile'});
  await ai.click({onboardWeekday:'1'});await ai.click({onboardWeekday:'4'});
  await ai.click({onboardPick:'sex',value:'male'});
  ai.handlers.input({target:{dataset:{onboard:'description'},type:'textarea',value:'Беспокоит колено после пробежки'}});
  assert.doesNotMatch(ai.root.innerHTML,/Уточнить с Yandex AI|Применить результат|Yandex AI выделил/);
  await ai.click({cmd:'onboard-save'});
  const optionalSaves=ai.requests.filter(x=>x.action==='onboarding');
  assert.equal(optionalSaves.length,1,'Free-text health note can save without AI analysis');
  assert.ok(optionalSaves[0].health_profile.affected.includes('knee'),
    'Literal knee mention is preserved as a conservative load restriction');
  assert.equal(ai.requests.filter(x=>x.action==='health_analyze').length,0,
    'Saving an ordinary health note never transmits it to Yandex AI');
  assert.equal(optionalSaves[0].timezone_confirmed,true);

   const diary=createClient(true,{trackHistory:true});await settle();
   await diary.click({nav:'progress'});await diary.click({date:'2026-10-23'});
   await diary.click({nav:'home'});await diary.click({cmd:'cardio-add'});
   await diary.click({cmd:'cardio-type',type:'Велосипед'});diary.input('cardio-min','60');
   await diary.click({cmd:'cardio'});await diary.click({nav:'progress'});
   assert.match(diary.root.innerHTML,/Кардио · Велосипед/,'Selected-date history refreshes after a successful cardio save');
   console.log('PASS v5 signed API, three tabs, nested plan, native onboarding, fullscreen fallback, workout, history and consent');
}
run().catch(e=>{console.error(e);process.exitCode=1});
