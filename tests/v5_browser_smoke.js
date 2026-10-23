'use strict';
/* Isolated real-browser QA for Telegram WebApp. Never uses production user data. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright-core');
const APP_HTML=fs.readFileSync(path.join(__dirname,'../web/v5-live.html'),'utf8');
const APP_JS=fs.readFileSync(path.join(__dirname,'../web/v5-live.js'),'utf8');
const OUT=path.join(__dirname,'../browser-shots');

function exampleState(onboarded=true) {
 return {
  agreed:onboarded,needs_health_profile:!onboarded,error:null,
  profile_raw:onboarded?{goal:'general',level:'beginner',days:'2',equipment:'gym',minutes:'45'}:{},
  profile:onboarded?{goal:'Поддерживать форму',level:'Новичок',days:'2',equipment:'В зале',minutes:'45'}:{},
  health_profile:onboarded?{affected:[],pain_score:0,symptom_course:'none',danger_signs:false,activity_cleared:false}:null,
  equipment_description:'',
  metrics:onboarded?{age:34,height_cm:181,weight_kg:82,sex:'male'}:{},
  tier_name:'Тестовый доступ',workout:null,history:[{id:8,date:'23.10.2026',title:'Силовая · ноги'}],
  plan_names:['Ноги и пресс'],next_day:'A',cycle_start:'2026-10-19',
  plan:[[{name:'Жим ногами',sets:3,low:10,high:12}]],
  calendar:[{id:2,week:1,day:'A',title:'Ноги и пресс',date:'2026-10-23',date_ru:'23.10.2026',status:'planned'}],
  stats:{total:1,last7:1,last30:1,sets:6}
 };
}
async function run(){
 const chrome=process.env.CHROME_PATH||[
  '/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium',
  '/opt/google/chrome/chrome'
 ].find(p=>fs.existsSync(p));
 assert.ok(chrome,'Chromium/Chrome executable not installed on runner');
 fs.mkdirSync(OUT,{recursive:true});
 let profileComplete=true,profileState=exampleState(true),posts=[];
 const server=http.createServer(async(req,res)=>{
  res.setHeader('Cache-Control','no-store');
  if(req.method==='GET'&&(req.url==='/'||req.url==='/mini/v5-live')){
   res.setHeader('Content-Type','text/html; charset=utf-8');res.end(APP_HTML);return;
  }
  if(req.method==='GET'&&req.url==='/mini/v5-live.js'){
   res.setHeader('Content-Type','text/javascript; charset=utf-8');res.end(APP_JS);return;
  }
  if(req.method==='POST'&&req.url==='/mini/api'){
   let raw='';for await(const chunk of req)raw+=chunk;
   let data;try{data=JSON.parse(raw)}catch(_){res.writeHead(400);res.end('{}');return}
   posts.push(data);
   let response={ok:true,data:profileState};
   if(data.action==='onboarding'){
    assert.equal(data.terms,true);
    assert.equal(data.privacy,true);
    assert.equal(data.health,true);
    assert.equal(data.answers.age_group,'adult');
    profileComplete=true;profileState=exampleState(true);
   }else if(data.action==='health_analyze'){
    response={ok:true,analysis:{affected:['knee'],pain_score:3,
      symptom_course:'stable',danger_signs:false,short_summary:'Беспокоит колено'}};
   }else if(data.action==='history_page'){
    response={ok:true,history:profileState.history,next_offset:null};
   }else if(data.action==='history_month'){
    response={ok:true,dates:['2026-10-23']};
   }else if(data.action==='detail'){
    response={ok:true,detail:{title:'Силовая',date:'23.10.2026',items:[]}};
   }else if(data.action!=='state') {
    response={ok:false,error:'Test fixture: unavailable action '+data.action};
   }
   res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify(response));return;
  }
  res.writeHead(404);res.end('not found');
 });
 const listen=()=>new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 await listen();
 const base='http://127.0.0.1:'+server.address().port;
 let browser;
 try{
  browser=await chromium.launch({headless:true,executablePath:chrome,args:['--no-sandbox','--disable-dev-shm-usage']});
  for(const size of [{width:393,height:852},{width:360,height:740}]){
   profileComplete=true;profileState=exampleState(true);posts=[];
   const context=await browser.newContext({viewport:size,isMobile:true,hasTouch:true,
     deviceScaleFactor:1});
   const page=await context.newPage();
   const errors=[];
   page.on('pageerror',e=>errors.push('pageerror: '+e.message));
   page.on('console',msg=>{if(msg.type()==='error')errors.push('console: '+msg.text())});
   await page.route('https://telegram.org/js/telegram-web-app.js',r=>
     r.fulfill({status:200,body:'',contentType:'text/javascript'}));
   await page.addInitScript(()=>{
    window.__fqFullscreen=0;
    window.Telegram={WebApp:{
     initData:'signed-for-browser-test',ready(){},expand(){},
     requestFullscreen(){window.__fqFullscreen++},
     isVersionAtLeast(){return true},onEvent(){},
     safeAreaInset:{top:24,bottom:8},contentSafeAreaInset:{top:0,bottom:0}
    }};
   });
   await page.goto(base+'/',{waitUntil:'load'});
   await page.waitForFunction(()=>document.querySelector('h1')?.textContent==='Сегодня');
   const nav=page.locator('.bottom-nav .nav-item');
   assert.equal(await nav.count(),3,'Exactly three bottom buttons');
   assert.deepEqual(await nav.allTextContents(),['Тренировки','Питание','Прогресс']);
   assert.equal(await page.evaluate(()=>window.__fqFullscreen),1,'Telegram fullscreen requested');
   const checkLayout=async(location)=>{
    const result=await page.evaluate(()=>{
     const width=document.documentElement.clientWidth;
     return {width,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,
      navRect:(()=>{const e=document.querySelector('.bottom-nav');return e&&e.getBoundingClientRect().toJSON()})()};
    });
    assert.ok(result.documentWidth<=result.width+1,location+' horizontal scroll: '+JSON.stringify(result));
    assert.ok(result.bodyWidth<=result.width+1,location+' body overflow: '+JSON.stringify(result));
    if(result.navRect)assert.ok(result.navRect.bottom<=size.height+1,location+' bottom nav outside viewport');
   };
   await checkLayout('home '+size.width);
   const exercise=await page.locator('.exercise').first().evaluate(e=>{
    const a=e.querySelector('.exercise-index'),b=e.querySelector('.exercise-name'),c=e.querySelector('.exercise-reps');
    return [a,b,c].map(n=>Math.round(n.getBoundingClientRect().top));
   });
   assert.ok(Math.max(...exercise)-Math.min(...exercise)<3,'Exercise number/name/reps must be aligned '+exercise);
   await page.screenshot({path:path.join(OUT,'home-'+size.width+'.png')});
   await page.getByRole('button',{name:'Мой план'}).click();
   await page.getByRole('button',{name:/19.10.2026/}).first().click();
   await page.locator('.week-details').first().waitFor();
   await checkLayout('plan');
   await page.screenshot({path:path.join(OUT,'plan-'+size.width+'.png')});
   await page.locator('.bottom-nav [data-nav="progress"]').click();
   await page.waitForFunction(()=>document.querySelector('h1')?.textContent==='Прогресс');
   await checkLayout('progress');
   await page.screenshot({path:path.join(OUT,'progress-'+size.width+'.png')});
   await page.locator('.bottom-nav [data-nav="food"]').click();
   await page.waitForFunction(()=>document.querySelector('h1')?.textContent==='Питание');
   await checkLayout('food');
   await page.screenshot({path:path.join(OUT,'food-'+size.width+'.png')});
   await page.getByRole('button',{name:'Профиль'}).click();
   await page.getByRole('button',{name:'Редактировать анкету'}).click();
   await page.locator('[data-onboard-pick="goal"]').first().waitFor();
   assert.equal(await page.locator('a[href="/mini/legacy"]').count(),0,'No 38.2 redirect');
   assert.equal(await page.locator('input#onboard-duration').count(),1,'Approved duration slider');
   await page.locator('[data-onboard-pick="goal"][data-value="muscle"]').click();
   assert.equal(await page.locator('[data-onboard-pick="goal"][data-value="muscle"]').getAttribute('aria-pressed'),'true');
   await checkLayout('profile questionnaire');
   await page.screenshot({path:path.join(OUT,'profile-'+size.width+'.png')});
   assert.equal(errors.length,0,'No JS errors: '+errors.join(' | '));
   await context.close();
  }
  // One-time questionnaire is rendered in Aluminium v5, never legacy 38.2.
  profileComplete=false;profileState=exampleState(false);
  const onboarding=await browser.newPage({viewport:{width:393,height:852}});
  await onboarding.route('https://telegram.org/js/telegram-web-app.js',r=>
   r.fulfill({status:200,body:'',contentType:'text/javascript'}));
  await onboarding.addInitScript(()=>{window.Telegram={WebApp:{
   initData:'signed-for-browser-test',ready(){},expand(){},onEvent(){},
   isVersionAtLeast(){return false}
  }}});
  await onboarding.goto(base+'/',{waitUntil:'load'});
  await onboarding.locator('button[data-cmd="onboard-save"]').waitFor();
  assert.equal(await onboarding.locator('a[href="/mini/legacy"]').count(),0);
  assert.equal(await onboarding.locator('.bottom-nav button').count(),0,'No bottom navigation before finishing onboarding');
  await onboarding.screenshot({path:path.join(OUT,'first-launch.png')});
  await onboarding.close();
  process.stdout.write('PASS browser: 3 tabs, nested plan, screen layout, fullscreen stub, profile, first launch (2 mobile sizes)\n');
 }finally{
  if(browser)await browser.close();
  await new Promise(resolve=>server.close(resolve));
 }
}
run().catch(e=>{console.error(e);process.exitCode=1});
