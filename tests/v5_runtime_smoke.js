'use strict';
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const js=fs.readFileSync('web/v5-live.js','utf8');

function createClient(auth=true){
 const requests=[],handlers={},fields=new Map(),failActions=new Set();
 let html='';
 const root={get innerHTML(){return html},set innerHTML(value){html=value;for(const field of fields.values())field.value=''},addEventListener(name,fn){handlers[name]=fn}};
 const doc={
  getElementById(id){return id==='app'?root:fields.get(id)||null},
  querySelector(){return null},
  activeElement:null
 };
 let workout=null;
 let metrics={age:34,height_cm:181,weight_kg:82};
 const client={
  root,handlers,fields,requests,
  failOnce(action){failActions.add(action)},
  async fetch(url,opts){
   assert.equal(url,'/mini/api');
   assert.equal(opts.method,'POST');
   assert.equal(opts.headers['X-Formiq-Init'],'signed-for-test');
   const p=JSON.parse(opts.body);requests.push(p);
   if(failActions.delete(p.action))return {ok:false,status:503,async json(){return {ok:false,error:'Временная ошибка API'}}};
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
    response={ok:true,patch:{workout}};
   }else if(p.action==='record'){
    workout={...workout,done:1,current:{...workout.current,set_no:2}};
    response={ok:true,patch:{workout}};
   }else if(p.action==='history_month')response={ok:true,dates:['2026-10-23'],month:p.month};
   else if(p.action==='history_page')response={ok:true,history:[{id:8,date:'23.10.2026',title:'Силовая'}],next_offset:null};
   else if(p.action==='detail')response={ok:true,detail:{title:'Силовая',date:'23.10.2026',items:[{name:'Жим ногами',result:'12 повт. · 60 кг'}]}};
   else if(p.action==='cardio'){assert.equal(p.type,'Велосипед');response={ok:true,data:state()};}
   else if(p.action==='save_metrics'){
    assert.ok(Object.keys(p.metrics).every(k=>['age','height_cm','weight_kg'].includes(k)));
    Object.assign(metrics,p.metrics);response={ok:true,patch:{metrics:{...metrics},zones:[]}};
   }
   else if(p.action==='finish'){workout=null;response={ok:true,data:state()}}
   else if(p.action==='skip')response={ok:true,patch:{workout}};
   else throw Error('Unexpected action: '+p.action);
   return {ok:true,status:200,async json(){return response}};
  }
 };
 const context={
  document:doc,
  window:{Telegram:{WebApp:{initData:auth?'signed-for-test':'',ready(){},expand(){}}},scrollTo(){},scrollBy(){},visualViewport:{offsetTop:0}},
  fetch:client.fetch,
  setTimeout(fn){return 1},clearTimeout(){},setInterval(fn){return 1},
  AbortController,Date,Set,Number,String,Array,Map,Object,RegExp,Math,
 };
 vm.runInNewContext(js,context,{filename:'web/v5-live.js',timeout:2000});
 client.click=async(dataset)=>{
  const target={closest(sel){return sel==='button'?{dataset}:null}};
  await handlers.click({target});
 };
 client.input=(id,value)=>fields.set(id,{id,value});
 return client;
}
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))};

async function run(){
 const blocked=createClient(false);
 assert.match(blocked.root.innerHTML,/Открой из Telegram/);
 assert.equal(blocked.requests.length,0);
 const app=createClient(true);
 await settle();
 assert.match(app.root.innerHTML,/Начать тренировку/);
 assert.ok(app.requests.find(x=>x.action==='state'));
 await app.click({cmd:'mood'});
 assert.match(app.root.innerHTML,/Самочувствие перед началом/);
 await app.click({cmd:'start-normal'});
 assert.match(app.root.innerHTML,/Жим ногами/);
 assert.match(app.root.innerHTML,/id="reps"[^>]*value=""/);
 app.input('reps','12');app.input('weight','60');
 app.failOnce('record');
 await app.click({cmd:'record'});
 assert.equal(app.fields.get('reps').value,'12','unsaved repetitions retained after error');
 assert.equal(app.fields.get('weight').value,'60','unsaved weight retained after error');
 assert.match(app.root.innerHTML,/Временная ошибка API/);
 await app.click({cmd:'record'});
 assert.ok(app.requests.some(x=>x.action==='record'&&x.reps===12&&x.weight===60));
 assert.match(app.root.innerHTML,/rest-count/);
 await app.click({cmd:'rest-skip'});
 assert.match(app.root.innerHTML,/Подход 2 из 2/);
 await app.click({nav:'home'});
 await app.click({cmd:'cardio-types'});
 await app.click({cmd:'cardio-type',type:'Велосипед'});
 app.input('cardio-min','60');app.input('cardio-hr','120');
 app.failOnce('cardio');
 await app.click({cmd:'cardio'});
 assert.equal(app.fields.get('cardio-min').value,'60','unsaved cardio duration retained');
 assert.equal(app.fields.get('cardio-hr').value,'120','unsaved average HR retained');
 await app.click({cmd:'cardio'});
 assert.ok(app.requests.some(x=>x.action==='cardio'&&x.type==='Велосипед'&&x.minutes===60));
 await app.click({nav:'progress'});
 assert.match(app.root.innerHTML,/19\.10\.2026 — 25\.10\.2026/,'Period button must show all 7 days, not just workout days');
 await app.click({nav:'profile'});
 assert.match(app.root.innerHTML,/data-nav="home"/,'User must be able to exit profile without Back');
 assert.match(app.root.innerHTML,/Изменить параметры/);
 await app.click({cmd:'profile-metrics-edit'});
 assert.match(app.root.innerHTML,/id="profile-age"[^>]*value="34"/);
 app.input('profile-age','34');app.input('profile-height_cm','181');app.input('profile-weight_kg','84,5');
 await app.click({cmd:'profile-metrics-save'});
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
 console.log('PASS v5 signed API, start, sets, retry-preserved fields, rest, history/calendar and cardio');
}
run().catch(e=>{console.error(e);process.exitCode=1});
