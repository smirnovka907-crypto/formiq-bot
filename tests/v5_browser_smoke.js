'use strict';
/* Isolated real-browser QA for Telegram WebApp. Never uses production user data. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright-core');
const APP_HTML=fs.readFileSync(path.join(__dirname,'../web/v5-live.html'),'utf8');
const APPROVED_HTML=fs.readFileSync(path.join(__dirname,'../docs/design/FORMIQ_Aluminium_v5_approved.html'),'utf8');
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
 let profileComplete=true,profileState=exampleState(true),posts=[],rejectCardioOnce=false,periodHistory=[];
 const server=http.createServer(async(req,res)=>{
  res.setHeader('Cache-Control','no-store');
  if(req.method==='GET'&&req.url==='/approved-reference'){
   res.setHeader('Content-Type','text/html; charset=utf-8');res.end(APPROVED_HTML);return;
  }
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
    assert.equal(data.answers.weekdays.length,Number(data.answers.days));
    assert.equal(new Set(data.answers.weekdays).size,data.answers.weekdays.length);
    profileComplete=true;profileState=exampleState(true);
    profileState.profile_raw={...data.answers};
    profileState.metrics={...profileState.metrics,...data.metrics,timezone:data.timezone};
    response={ok:true,data:profileState};
   }else if(data.action==='health_analyze'){
    response={ok:true,analysis:{affected:['knee'],pain_score:3,
      symptom_course:'stable',danger_signs:false,short_summary:'Беспокоит колено'}};
   }else if(data.action==='feedback'){response={ok:true,saved:true,message:'Спасибо! Отзыв сохранён.'};
    }else if(data.action==='history_page'){
    response={ok:true,history:profileState.history,next_offset:null};
   }else if(data.action==='history_month'){
    response={ok:true,dates:['2026-10-23']};
   }else if(data.action==='progress_series'){
    response={ok:true,exercises:profileState.finishedWeightHistory||[]};
   }else if(data.action==='period_list'){
    assert.equal(profileState.metrics.sex,'female','Female calendar only after consented sex selection');
    response={ok:true,periods:periodHistory,next_period:null};
   }else if(data.action==='period_save'){
    assert.equal(profileState.metrics.sex,'female');
    if(data.id){
     const record=periodHistory.find(x=>x.id===data.id);
     assert.ok(record);record.start=data.start;record.end=data.end;
    }else periodHistory.unshift({id:periodHistory.length+1,start:data.start,end:data.end});
    response={ok:true,periods:periodHistory,next_period:null};
   }else if(data.action==='period_delete'){
    assert.equal(profileState.metrics.sex,'female');
    const index=periodHistory.findIndex(x=>x.id===data.id);
    assert.ok(index>=0,'Only an existing owner period can be deleted');
    periodHistory.splice(index,1);
    response={ok:true,periods:periodHistory,next_period:null};
   }else if(data.action==='detail'){
    const item=profileState.history.find(x=>x.id===data.id);
    response={ok:true,detail:{title:item?.title||'Силовая',date:'23.10.2026',items:[{name:'Записано в тестовом дневнике',result:'60 мин'}]}};
   }else if(data.action==='start'){
    assert.equal(data.mood,'normal');
    profileState.workout={id:9,done:0,total:2,finished:false,title:'Ноги и пресс',
     exercises:[{position:0,name:'Жим ногами',done:0,skipped:0,total:2}],current:{name:'Жим ногами',position:0,set_no:1,set_count:2,low:10,high:12,unit:'reps',rest_seconds:90}};
    response={ok:true,patch:{workout:profileState.workout}};
   }else if(data.action==='record'){
    assert.equal(data.expected_workout,9);assert.equal(data.expected_set,1);
    assert.equal(data.reps,12);assert.equal(data.weight,60);
    profileState.workout={...profileState.workout,done:1,exercises:[{position:0,name:'Жим ногами',done:1,skipped:0,total:2}],rest_remaining_seconds:89,
     current:{...profileState.workout.current,set_no:2}};
    response={ok:true,patch:{workout:profileState.workout}};
   }else if(data.action==='finish'){
    profileState.workout=null;
    profileState.history.unshift({id:9,date:'23.10.2026',title:'Силовая · завершена в браузере'});
    profileState.stats.total++;
    profileState.finishedWeightHistory=[{key:'leg_press',name:'Жим ногами',
     points:[{date:'2026-10-20',weight:55},{date:'2026-10-23',weight:60}]}];
   }else if(data.action==='cardio'){
    assert.equal(data.type,'Велосипед');assert.equal(data.minutes,60);assert.equal(data.avg_hr,120);
    if(rejectCardioOnce){rejectCardioOnce=false;response={ok:false,error:'Тест: кардио не сохранено'}}
    else profileState.history.unshift({id:10,date:'23.10.2026',title:'Дополнительная тренировка · Велосипед · 60 мин'});
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
     requestFullscreen(){
      window.__fqFullscreen++;
      this.isFullscreen=true;
      this.contentSafeAreaInset.top=52;
     },
     isVersionAtLeast(){return true},
     onEvent(name,callback){(window.__fqTelegramEvents||(window.__fqTelegramEvents={}))[name]=callback},
     safeAreaInset:{top:24,bottom:8},contentSafeAreaInset:{top:0,bottom:0}
    }};
   });
   // Always pair the same viewport and UI state. Neither page is cropped or resized.
   // The reference contains illustrative values, while the live page uses isolated signed API fixtures.
   const pairedManifest=[];
   const matchedShot=async(name,setupReference,options={})=>{
    const ref=await context.newPage();
    await ref.goto(base+'/approved-reference',{waitUntil:'load'});
    // The approved reference stores its demo workout in browser localStorage.
    // Remove only that disposable preview key before each independent matched state.
    await ref.evaluate(()=>localStorage.removeItem('formiq_preview_active_workout_v2'));
    await ref.reload({waitUntil:'load'});
    await ref.waitForFunction(()=>document.querySelector('h1')?.textContent==='Сегодня');
    if(setupReference)await setupReference(ref);
    const align=async(p,selector)=>{
     if(selector)await p.locator(selector).first().evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));
     else await p.evaluate(y=>window.scrollTo({top:y,behavior:'instant'}),options.scrollY||0);
    };
    await align(ref,options.referenceAnchor);
    await align(page,options.liveAnchor);
    const refScroll=await ref.evaluate(()=>window.scrollY);
    const realScroll=await page.evaluate(()=>window.scrollY);
    const referenceFile='pair-approved-'+name+'-'+size.width+'.png';
    const realFile='pair-live-'+name+'-'+size.width+'.png';
    for(const [p,file] of [[ref,referenceFile],[page,realFile]]){
     const bytes=await p.screenshot({path:path.join(OUT,file),fullPage:false,animations:'disabled'});
     assert.equal(bytes.readUInt32BE(16),size.width,'Full-width screenshot, not cropped');
     assert.equal(bytes.readUInt32BE(20),size.height,'Full-height viewport, not cropped');
    }
    // Preserve the complete document for every distinct screen, not merely the
    // visible 740/852 px viewport. Only repeated scroll checkpoints are omitted.
    const fullPage=!name.startsWith('questionnaire-scroll-')&&name!=='questionnaire-weekdays';
    const fullReferenceFile=fullPage?'pair-approved-'+name+'-'+size.width+'-full.png':null;
    const fullRealFile=fullPage?'pair-live-'+name+'-'+size.width+'-full.png':null;
    const fullPageHeights=[];
    if(fullPage)for(const [p,file] of [[ref,fullReferenceFile],[page,fullRealFile]]){
     const image=await p.screenshot({path:path.join(OUT,file),fullPage:true,animations:'disabled'});
     assert.equal(image.readUInt32BE(16),size.width,'Uncropped full-page screenshot has native width');
     assert.ok(image.readUInt32BE(20)>=size.height,'Uncropped document must include entire viewport');
     fullPageHeights.push(image.readUInt32BE(20));
    }
    pairedManifest.push({name,width:size.width,height:size.height,referenceFile,realFile,
     fullReferenceFile,fullRealFile,fullPageHeights,
     referenceScrollY:refScroll,realScrollY:realScroll,
     referenceAnchor:options.referenceAnchor||null,liveAnchor:options.liveAnchor||null,
     mode:options.referenceAnchor||options.liveAnchor?'corresponding feature top':'same numeric scroll',
     note:options.note||'Approved HTML demo vs isolated API fixture'});
    await ref.close();
   };
   // Store approved prototype beside the real-app screenshots for human review.
   // This reference route is test-only and never deployed to the Mini App.
   const reference=await context.newPage();
   await reference.goto(base+'/approved-reference',{waitUntil:'load'});
   await reference.waitForFunction(()=>document.querySelector('h1')?.textContent==='Сегодня');
   await reference.screenshot({path:path.join(OUT,'approved-home-'+size.width+'.png')});
   for(const [nav,name] of [['food','food'],['progress','progress']]){
    await reference.locator('.bottom-nav [data-nav="'+nav+'"]').click();
    await reference.screenshot({path:path.join(OUT,'approved-'+name+'-'+size.width+'.png')});
   }
   await reference.locator('[data-act="history-calendar"]').click();
   await reference.locator('.history-cal-inline').scrollIntoViewIfNeeded();
   await reference.screenshot({path:path.join(OUT,'approved-calendar-'+size.width+'.png')});
   await reference.locator('[data-act="history-calendar"]').click();
   await reference.locator('[data-act="history-open"]').click();
   await reference.locator('.history-modal .history-scroll').waitFor();
   await reference.screenshot({path:path.join(OUT,'approved-history-modal-'+size.width+'.png')});
   await reference.locator('[data-act="history-close"]').click();
   await reference.locator('[data-week="1"]').first().click();
   await reference.locator('.plan-period-days').scrollIntoViewIfNeeded();
   await reference.screenshot({path:path.join(OUT,'approved-plan-'+size.width+'.png')});
   await reference.locator('.bottom-nav [data-nav="home"]').click();
   await reference.locator('[data-act="profile"]').first().click();
   await reference.screenshot({path:path.join(OUT,'approved-profile-'+size.width+'.png')});
   await reference.locator('.bottom-nav [data-nav="home"]').click();
   await reference.locator('[data-act="home-start"]').click();
   await reference.locator('#workout-entry').waitFor();
   await reference.screenshot({path:path.join(OUT,'approved-workout-entry-'+size.width+'.png')});
   await reference.locator('#workout-weight').fill('60');
   await reference.locator('#workout-reps').fill('12');
   await reference.locator('[data-act="set-done"]').click();
   await reference.locator('#rest-clock').waitFor();
   await reference.screenshot({path:path.join(OUT,'approved-workout-rest-'+size.width+'.png')});
   await reference.close();
   await page.goto(base+'/',{waitUntil:'load'});
   await page.waitForFunction(()=>/Доброе утро|Добрый день|Добрый вечер|Доброй ночи/.test(document.querySelector('h1')?.textContent||''));
   const nav=page.locator('.bottom-nav .nav-item');
   assert.equal(await nav.count(),3,'Exactly three bottom buttons');
   assert.deepEqual(await nav.allTextContents(),['Тренировки','Питание','Прогресс']);
   assert.equal(await page.evaluate(()=>window.__fqFullscreen),1,'Telegram fullscreen requested');
   const safeHeader=await page.evaluate(()=>{
    const header=document.querySelector('.header').getBoundingClientRect();
    const brand=document.querySelector('.brand').getBoundingClientRect();
    const profile=document.querySelector('.profile-open').getBoundingClientRect();
    return {top:header.top,brandTop:brand.top,profileTop:profile.top,
      contentTop:Telegram.WebApp.contentSafeAreaInset.top};
   });
   assert.ok(safeHeader.top>=24+52+18-1,'Header must clear system + Telegram top controls: '+JSON.stringify(safeHeader));
   assert.ok(safeHeader.brandTop>=24+52,'Logo below Telegram controls');
   assert.ok(safeHeader.profileTop>=24+52,'Profile button below Telegram controls');
   // Telegram may report changed insets after fullscreen or orientation.
   const shifted=await page.evaluate(()=>{
    Telegram.WebApp.contentSafeAreaInset.top=76;
    window.__fqTelegramEvents.contentSafeAreaChanged();
    return document.querySelector('.header').getBoundingClientRect().top;
   });
   assert.ok(shifted>=24+76+18-1,'Header must follow content safe-area change: '+shifted);
   const fallback=await page.evaluate(()=>{
    Telegram.WebApp.contentSafeAreaInset.top=0;
    window.__fqTelegramEvents.contentSafeAreaChanged();
    return document.querySelector('.header').getBoundingClientRect().top;
   });
   assert.ok(fallback>=24+64+18-1,'Telegram fullscreen buttons protected when inset temporarily zero: '+fallback);
   await page.evaluate(()=>{
    Telegram.WebApp.contentSafeAreaInset.top=52;
    window.__fqTelegramEvents.contentSafeAreaChanged();
   });
   const checkInputAlignment=async()=>{
    const boxes=await page.locator('.workout-entry .workout-input-grid .field').evaluateAll(els=>els.map(el=>{
     const label=el.querySelector('span').getBoundingClientRect(),input=el.querySelector('input').getBoundingClientRect();
     return {labelTop:label.top,labelBottom:label.bottom,inputTop:input.top,inputBottom:input.bottom,inputHeight:input.height,inputWidth:input.width};
    }));
    assert.equal(boxes.length,2,'Strength entry has two aligned fields');
    assert.ok(Math.abs(boxes[0].inputTop-boxes[1].inputTop)<1,'Input tops aligned: '+JSON.stringify(boxes));
    assert.ok(Math.abs(boxes[0].inputHeight-boxes[1].inputHeight)<1,'Input heights match');
    assert.ok(Math.abs(boxes[0].labelTop-boxes[1].labelTop)<1,'Labels share top baseline');
    assert.ok(Math.abs(boxes[0].labelBottom-boxes[1].labelBottom)<1,'Labels share bottom baseline');
    assert.ok(boxes.every(b=>b.inputWidth>90&&b.inputHeight>=49),'Inputs remain touch-accessible');
   };
   const checkFooterReachable=async(names)=>{
    for(const cmd of names){
     // Align the actual control inside the unobstructed safe viewport, not merely
     // against the document bottom: actions now precede the exercise overview.
     const position=await page.evaluate(cmd=>{
      const el=document.querySelector('[data-cmd="'+cmd+'"]');
      if(!el)return {cmd,exists:false};
      const nav=document.querySelector('.bottom-nav');
      const navTop=nav?.getBoundingClientRect().top??innerHeight;
      const b=el.getBoundingClientRect();
      const idealTop=Math.max(100,navTop-b.height-24);
      if(b.bottom>navTop-3||b.top<0)window.scrollBy({top:b.top-idealTop,behavior:'instant'});
      const rect=el.getBoundingClientRect(),bottom=nav?.getBoundingClientRect().top??innerHeight;
      return {cmd,exists:true,top:rect.top,bottom:rect.bottom,height:rect.height,width:rect.width,navTop:bottom};
     },cmd);
     assert.ok(position.exists&&position.top>=0&&position.height>=44&&position.width>=104&&position.bottom<=position.navTop-3,
       'All workout actions must be scroll-reachable above fixed tabs: '+JSON.stringify(position));
    }
   };
   const checkLayout=async(location)=>{
    const result=await page.evaluate(()=>{
     const width=document.documentElement.clientWidth;
     return {width,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,
      navRect:(()=>{const e=document.querySelector('.bottom-nav');return e&&e.getBoundingClientRect().toJSON()})()};
    });
    assert.ok(result.documentWidth<=result.width+1,location+' horizontal scroll: '+JSON.stringify(result));
    assert.ok(result.bodyWidth<=result.width+1,location+' body overflow: '+JSON.stringify(result));
    // Detect side overflows at any scroll position, including hidden below the fold.
    const geometry=await page.evaluate(()=>{
     const width=document.documentElement.clientWidth;
     const nodes=document.querySelectorAll('.surface,.fq-live-dialog,.bottom-nav,.field input,.field select,.field textarea,.button-main,.button-subtle,.choice');
     return Array.from(nodes).flatMap(el=>{
      const style=getComputedStyle(el),b=el.getBoundingClientRect();
      if(style.display==='none'||b.width===0||b.height===0)return [];
      const offscreen=b.left<-.8||b.right>width+.8;
      const undersized=el.matches('.button-main,.button-subtle')&&(b.height<43||b.width<44);
      return offscreen||undersized?[{className:el.className,tag:el.tagName,rect:{left:b.left,right:b.right,height:b.height,width:b.width},offscreen,undersized}]:[];
     }).slice(0,12);
    });
    assert.deepEqual(geometry,[],location+' misaligned mobile controls: '+JSON.stringify(geometry));
    if(result.navRect)assert.ok(result.navRect.bottom<=size.height+1,location+' bottom nav outside viewport');
   };
   await checkLayout('home '+size.width);
   const exercise=await page.locator('.exercise').first().evaluate(e=>{
    const a=e.querySelector('.exercise-name'),b=e.querySelector('.exercise-reps');
    return [a,b].map(n=>Math.round(n.getBoundingClientRect().top));
   });
   assert.ok(Math.max(...exercise)-Math.min(...exercise)<3,'Exercise name and target must align '+exercise);
   assert.equal(await page.locator('.cardio-inline').count(),1,'Cardio must be embedded on the workouts screen');
   assert.equal(await page.locator('.cardio-inline #cardio-min').count(),1);
   assert.equal(await page.locator('.cardio-inline #cardio-hr').count(),1);
   assert.equal(await page.locator('#training-plan').count(),1,'Workouts contains the four-week plan');
   assert.equal(await page.getByRole('button',{name:'Мой план'}).count(),0,'No obsolete plan link on Today');
   await page.screenshot({path:path.join(OUT,'home-'+size.width+'.png')});
   await matchedShot('home',null);
   await page.locator('#cardio-min').focus();
   assert.equal(await page.evaluate(()=>document.body.classList.contains('cardio-typing')),true,'Typing class is set for inline cardio');
   assert.equal(await page.locator('.bottom-nav').evaluate(e=>getComputedStyle(e).visibility),'hidden','Bottom nav moves out of keyboard');
   await page.locator('#cardio-min').evaluate(e=>e.blur());
   assert.equal(await page.evaluate(()=>document.body.classList.contains('cardio-typing')),false,'Cardio typing class clears');
   assert.equal(await page.locator('.bottom-nav').evaluate(e=>getComputedStyle(e).visibility),'visible','Bottom nav restores');
   const planOrder=await page.evaluate(()=>{
    const card=document.querySelector('#training-plan');
    return {before:card?.previousElementSibling?.querySelector('h2')?.textContent};
   });
   assert.equal(planOrder.before,'Дополнительная тренировка','Plan directly follows extra training');
   await page.getByRole('button',{name:/19.10.2026/}).first().click();
   await page.locator('.week-details').first().waitFor();
    assert.equal(await page.getByText('Garmin Connect',{exact:true}).count(),0);
    assert.equal(await page.getByText('Женский календарь',{exact:true}).count(),0);
   const planButtons=await page.locator('.fq-plan-period-grid .week-group>button').evaluateAll(items=>items.map(el=>el.getBoundingClientRect().toJSON()));
   assert.equal(planButtons.length,4,'Four actual server-dated periods');
   assert.ok(Math.abs(planButtons[0].top-planButtons[1].top)<1,'Periods use two columns like v5');
   assert.ok(Math.abs(planButtons[2].top-planButtons[3].top)<1,'Second row is aligned');
   assert.ok(planButtons[2].top>planButtons[0].top,'Periods use two rows');
   assert.ok(planButtons.every(b=>Math.abs(b.width-planButtons[0].width)<2&&
     Math.abs(b.height-planButtons[0].height)<2),'All four buttons use identical sizes');
   const gridRect=await page.locator('#training-plan .fq-plan-period-grid').boundingBox();
   assert.ok((await page.locator('.week-details').boundingBox()).width>=gridRect.width-2,
     'Days expand across both card columns');
   await checkLayout('plan');
   await page.screenshot({path:path.join(OUT,'plan-'+size.width+'.png')});
   await page.locator('.bottom-nav [data-nav="progress"]').click();
   await page.waitForFunction(()=>document.querySelector('h1')?.textContent==='Прогресс');
   assert.equal(await page.locator('#training-plan').count(),0,'Progress no longer contains training plan');
   await page.locator('.fq-empty-chart').waitFor();
   assert.equal(await page.locator('.fq-progress-chart').count(),0,'No fabricated working-weight graph');
   await checkLayout('progress');
   await page.screenshot({path:path.join(OUT,'progress-'+size.width+'.png')});
   await matchedShot('progress',async ref=>ref.locator('.bottom-nav [data-nav="progress"]').click());
   await page.locator('.bottom-nav [data-nav="food"]').click();
   await page.waitForFunction(()=>document.querySelector('h1')?.textContent==='Питание');
   assert.equal(await page.locator('#food-text').count(),1,'Manual food input is available');
   assert.equal(await page.locator('#food-date').count(),1,'Nutrition includes date selector');
   assert.equal(await page.locator('#nutrition-consent').count(),0,'No duplicate Yandex consent');
   assert.equal(await page.locator('.nutrition-ring').count(),0,'No fabricated calorie display');
   await checkLayout('food');
   await page.screenshot({path:path.join(OUT,'food-'+size.width+'.png')});
   // Nutrition now has a new approved manual diary, not the retired empty-state reference.
   assert.equal(await page.locator('.profile-open').evaluate(el=>getComputedStyle(el).position),'static',
    'Profile shortcut must scroll with header instead of covering content');
   await page.getByRole('button',{name:'Профиль'}).click();
   assert.equal(await page.locator('.connection-row').count(),0,'No unavailable integration cards');
    assert.equal(await page.getByText('Профиль:',{exact:true}).count(),1);
   assert.equal(await page.locator('.profile-open').isVisible(),false,
    'Profile shortcut must not cover editable questionnaire fields');
   await page.locator('[data-onboard-pick="goal"]').first().waitFor();
   assert.equal(await page.locator('a[href="/mini/legacy"]').count(),0,'No 38.2 redirect');
   assert.equal(await page.locator('select[data-onboard="minutes"]').count(),1,'Approved 20–120 minute dropdown');
   assert.equal(await page.locator('[data-onboard-weekday]').count(),7,'Seven weekday controls');
   const weekdayRects=await page.locator('[data-onboard-weekday]').evaluateAll(buttons=>buttons.map(b=>b.getBoundingClientRect().toJSON()));
   assert.ok(weekdayRects.every(r=>r.height>=44),'Weekday controls have accessible touch height');
   assert.ok(weekdayRects.every(r=>Math.abs(r.top-weekdayRects[0].top)<1),'Weekdays fit into one row');
   await page.locator('[data-onboard-pick="goal"][data-value="muscle"]').click();
   assert.equal(await page.locator('[data-onboard-pick="goal"][data-value="muscle"]').getAttribute('aria-pressed'),'true');
   const sexButtons=await page.locator('.fq-sex-options .choice').evaluateAll(els=>els.map(x=>x.getBoundingClientRect().toJSON()));
   assert.equal(sexButtons.length,2,'Exactly two gender choices');
   assert.ok(sexButtons.every(b=>Math.abs(b.top-sexButtons[0].top)<1),'All sex choices align in a single row');
   assert.ok(sexButtons.every(b=>Math.abs(b.width-sexButtons[0].width)<2&&Math.abs(b.height-sexButtons[0].height)<2),
     'All sex choices have symmetric geometry');
   const equipmentButtons=await page.locator('.fq-equipment-options .choice').evaluateAll(els=>els.map(x=>x.getBoundingClientRect().toJSON()));
   assert.equal(equipmentButtons.length,2,'Only home and gym choices');
   assert.ok(equipmentButtons.every(b=>Math.abs(b.top-equipmentButtons[0].top)<1),
     'Training locations do not leave a dangling third button');
   assert.ok(equipmentButtons.every(b=>Math.abs(b.width-equipmentButtons[0].width)<2&&Math.abs(b.height-equipmentButtons[0].height)<2),
     'Training location buttons are equal-size');
   await checkLayout('profile questionnaire');
   await page.evaluate(()=>window.scrollTo(0,0));
   await page.screenshot({path:path.join(OUT,'profile-'+size.width+'.png')});
   await matchedShot('questionnaire-top',async ref=>ref.locator('[data-act="profile"]').first().click());
   await page.evaluate(()=>window.scrollTo(0,360));
   await page.screenshot({path:path.join(OUT,'profile-scroll-'+size.width+'.png')});
   for(const y of [360,720,1200])await matchedShot('questionnaire-scroll-'+y,async ref=>ref.locator('[data-act="profile"]').first().click(),
    {scrollY:y,note:'Same exact scroll offset; reference profile is an editable prototype, real form contains required consent'});
   await page.locator('.fq-weekday-options').scrollIntoViewIfNeeded();
   await checkLayout('weekday selector '+size.width);
   await page.screenshot({path:path.join(OUT,'weekdays-'+size.width+'.png')});
   await matchedShot('questionnaire-weekdays',async ref=>ref.locator('[data-act="profile"]').first().click(),
    {referenceAnchor:'.weekdays',liveAnchor:'.fq-weekday-options',note:'Weekday selector aligned to viewport top; real questionnaire requires explicit weekdays'});
   await page.locator('.bottom-nav [data-nav="home"]').click();
   await page.getByRole('button',{name:'Начать тренировку',exact:true}).click();
   await page.getByRole('button',{name:'Хорошо',exact:true}).click();
   await page.locator('#reps').waitFor({state:'visible'});
   await page.locator('.fq-live-overlay').waitFor({state:'detached'});
   assert.equal(await page.locator('.workout-plan-list .workout-plan-row').count(),1,'Actual workout exercise overview');
   assert.deepEqual(await page.locator('.bottom-nav .nav-item').allTextContents(),
    ['Тренировки','Питание','Прогресс'],'Approved three tabs remain visible during active sets');
   await checkInputAlignment();
   await page.evaluate(()=>window.scrollTo(0,0));
   const initialSetControls=await page.evaluate(()=>{
    const nav=document.querySelector('.bottom-nav').getBoundingClientRect();
    return {navTop:nav.top,actions:['record','skip-confirm','finish-confirm'].map(cmd=>{
      const box=document.querySelector('[data-cmd="'+cmd+'"]').getBoundingClientRect();
      return {cmd,top:box.top,bottom:box.bottom};
    })};
   });
   // Telegram safe-area padding reduces the initially visible area on short
   // phones. Keep the primary record action visible, and verify secondary
   // actions remain reachable by scrolling, never hidden under the tab bar.
   const primary=initialSetControls.actions.find(b=>b.cmd==='record');
   assert.ok(primary.top>=0&&primary.bottom<=initialSetControls.navTop-3,
     'Primary record action must remain visible above tabs: '+JSON.stringify(initialSetControls));
   assert.equal(await page.locator('.workout-secondary-actions').count(),1,
     'Active actions grouped before the exercise summary');
   await checkFooterReachable(['skip-confirm','finish-confirm']);
   await checkLayout('active workout');
   await page.screenshot({path:path.join(OUT,'workout-entry-'+size.width+'.png')});
   await matchedShot('workout-entry',async ref=>{await ref.locator('[data-act="home-start"]').click();await ref.locator('#workout-entry').waitFor();});
   // The server-backed workout and unsaved input drafts survive temporary tab navigation.
   await page.locator('#reps').fill('12');await page.locator('#weight').fill('60');
   await page.locator('.bottom-nav [data-nav="food"]').click();
   await page.locator('.bottom-nav [data-nav="home"]').click();
   await page.locator('#reps').waitFor({state:'visible'});
   assert.equal(await page.locator('#reps').inputValue(),'12','Draft repetitions survive tab switch');
   assert.equal(await page.locator('#weight').inputValue(),'60','Draft load survives tab switch');
   await page.locator('#reps').fill('12');await page.locator('#weight').fill('60');
   await page.getByRole('button',{name:'Подход выполнен',exact:true}).click();
   await page.locator('#rest-count').waitFor();
   assert.equal(await page.locator('.bottom-nav .nav-item').count(),3,'Three tabs during rest');
   await checkFooterReachable(['rest-skip','skip-confirm','finish-confirm']);
   await page.evaluate(()=>window.scrollTo(0,0));
   const restFirstView=await page.evaluate(()=>{
    const nav=document.querySelector('.bottom-nav').getBoundingClientRect();
    const btns=['skip-confirm','finish-confirm'].map(cmd=>document.querySelector('[data-cmd="'+cmd+'"]').getBoundingClientRect());
    return {navTop:nav.top,buttons:btns.map(b=>({top:b.top,bottom:b.bottom}))};
   });
   assert.ok(restFirstView.buttons.every(b=>b.top>=0&&b.bottom<=restFirstView.navTop-3),
     'Secondary rest controls must be visible without scrolling under fixed tabs: '+JSON.stringify(restFirstView));
   await checkLayout('workout rest timer');
   await page.screenshot({path:path.join(OUT,'workout-rest-'+size.width+'.png')});
   await matchedShot('workout-rest',async ref=>{
    await ref.locator('[data-act="home-start"]').click();await ref.locator('#workout-weight').fill('60');await ref.locator('#workout-reps').fill('12');
    await ref.locator('[data-act="set-done"]').click();await ref.locator('#rest-clock').waitFor();
   });
   await page.getByRole('button',{name:'Пропустить отдых',exact:true}).click();
   assert.equal(await page.locator('#reps').inputValue(),'','Saved repetitions are cleared for the next set');
   await page.getByRole('button',{name:'Завершить досрочно',exact:true}).click();
   await page.locator('.fq-live-dialog').getByRole('button',{name:'Завершить',exact:true}).click();
   await page.getByText('Силовая · завершена в браузере',{exact:true}).waitFor();
   await page.locator('.fq-progress-chart').waitFor();
   assert.match(await page.locator('.fq-progress-chart').getAttribute('aria-label'),/60 кг/);
   await checkLayout('real saved weight chart');
   await page.screenshot({path:path.join(OUT,'progress-real-weights-'+size.width+'.png')});
   await matchedShot('progress-recorded',async ref=>ref.locator('.bottom-nav [data-nav="progress"]').click(),
    {note:'Live chart uses actual isolated completed sets; approved example values are illustrative'});
   const monthReply=page.waitForResponse(resp=>{
    if(!resp.url().endsWith('/mini/api'))return false;
    try{return JSON.parse(resp.request().postData()||'{}').action==='history_month'}
    catch(_e){return false}
   });
   await page.getByRole('button',{name:'По датам'}).click();
   await monthReply; // Wait for the owner-scoped month query before moving the viewport.
   await page.waitForFunction(()=>!!document.querySelector('.history-cal-inline'));
   await page.evaluate(()=>document.querySelector('.history-cal-inline')?.scrollIntoView({block:'start'}));
   const calendarTouch=await page.locator('.history-cal-inline .calendar-controls button, .history-cal-inline .history-cal-grid button').evaluateAll(items=>items.map(el=>el.getBoundingClientRect().height));
   assert.ok(calendarTouch.every(h=>h>=44),'Calendar arrows and every day must be >=44 px');
   await checkLayout('history calendar');
   await page.screenshot({path:path.join(OUT,'history-calendar-'+size.width+'.png')});
   await matchedShot('history-calendar',async ref=>{
    await ref.locator('.bottom-nav [data-nav="progress"]').click();await ref.locator('[data-act="history-calendar"]').click();
   },{referenceAnchor:'.history-cal-inline',liveAnchor:'.history-cal-inline'});
   await page.getByRole('button',{name:'Вся история →'}).click();
   await page.locator('.history-modal .history-scroll').waitFor();
   await page.locator('.history-modal .fq-history-action').first().waitFor(); // Snapshot real rows, not loading placeholder.
   await checkLayout('history bottom sheet');
   assert.equal(await page.locator('.history-modal [role="region"]').count(),1,'Scroll within history sheet');
   const sheet=await page.locator('.history-modal').evaluate(e=>{
    const r=e.getBoundingClientRect();
    const btn=e.querySelector('.history-close').getBoundingClientRect();
    return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,buttonHeight:btn.height};
   });
   assert.ok(sheet.left>=-.5&&sheet.right<=size.width+.5&&sheet.top>=0&&sheet.bottom<=size.height+1&&sheet.buttonHeight>=44,
     'History dialog/close button must fit the viewport and be touchable: '+JSON.stringify(sheet));
   await page.screenshot({path:path.join(OUT,'history-modal-'+size.width+'.png')});
   await matchedShot('history-modal',async ref=>{await ref.locator('.bottom-nav [data-nav="progress"]').click();await ref.locator('[data-act="history-open"]').click();});
   await page.getByRole('button',{name:'Закрыть историю'}).click();
   await page.locator('.bottom-nav [data-nav="home"]').click();
   const cardioTypes=page.locator('.cardio-inline [data-cmd="cardio-types"]');
   assert.equal(await cardioTypes.textContent(),'Выбрать упражнение','New additional training starts without a selected type');
   await cardioTypes.click();
   await page.locator('.cardio-inline [data-cmd="cardio-type"][data-type="Велосипед"]').click();
   await page.locator('#cardio-min').fill('60');await page.locator('#cardio-hr').fill('120');
   rejectCardioOnce=true;
   await page.getByRole('button',{name:'Сохранить тренировку',exact:true}).click();
   await page.getByRole('alert').filter({hasText:'Тест: кардио не сохранено'}).waitFor();
   assert.equal(await page.locator('#cardio-min').inputValue(),'60','Failed save preserves cardio minutes');
   assert.equal(await page.locator('#cardio-hr').inputValue(),'120','Failed save preserves heart rate');
   await page.getByRole('button',{name:'Сохранить тренировку',exact:true}).click();
   assert.equal(await page.locator('.cardio-inline').count(),1,'Cardio editor remains available after save');
   await page.waitForFunction(()=>document.querySelector('#cardio-min')?.value==='','Saved cardio must clear editor');
   assert.equal(await page.locator('#cardio-hr').inputValue(),'','Saved heart rate must clear');
   await page.locator('.bottom-nav [data-nav="progress"]').click();
   await page.getByRole('button',{name:/Дополнительная тренировка · Велосипед · 60 мин/}).click();
   await page.getByText('Записано в тестовом дневнике',{exact:true}).waitFor();
   assert.equal(profileState.history.filter(x=>x.id===10).length,1,'Retry of a rejected request creates one cardio entry');
   assert.equal(errors.length,0,'No JS errors: '+errors.join(' | '));
   fs.writeFileSync(path.join(OUT,'paired-manifest-'+size.width+'.json'),JSON.stringify({
    approved:'docs/design/FORMIQ_Aluminium_v5_approved.html',actual:'web/v5-live.html',
    viewport:size,telegramSafeArea:{top:24,bottom:8},deviceScaleFactor:1,viewportPngUncropped:true,fullPagePngUncropped:true,
    states:pairedManifest
   },null,2));
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
  assert.equal(await onboarding.getByText(/Раньше сохранялось только количество/).count(),0,'First launch has no legacy-profile explanation');
  assert.equal(await onboarding.locator('a[href="/mini/legacy"]').count(),0);
  assert.equal(await onboarding.locator('.bottom-nav button').count(),0,'No bottom navigation before finishing onboarding');
  assert.equal(await onboarding.locator('.profile-open').isVisible(),false,'No profile shortcut before onboarding is complete');
  await onboarding.locator('.profile-open').evaluate(el=>el.click());
  assert.equal(await onboarding.locator('button[data-cmd="onboard-save"]').count(),1,
   'A synthetic header click must not bypass mandatory onboarding');
  assert.equal(await onboarding.locator('.bottom-nav button').count(),0,'No tabs after attempted onboarding bypass');
  await onboarding.screenshot({path:path.join(OUT,'first-launch.png')});
  await onboarding.locator('[data-onboard="birth_date"]').fill('1992-10-20');
  await onboarding.locator('[data-onboard="height_cm"]').fill('181');
  await onboarding.locator('[data-onboard="weight_kg"]').fill('82');
  for(const field of ['terms','privacy','health'])await onboarding.locator('[data-onboard="'+field+'"]').check();
  await onboarding.locator('[data-onboard-pick="sex"][data-value="female"]').click();
  await onboarding.locator('body.theme-female').waitFor();
  await onboarding.locator('[data-onboard="minutes"]').selectOption('120');
  await onboarding.getByRole('button',{name:'Сохранить анкету',exact:true}).click();
  await onboarding.getByRole('alert').filter({hasText:'Выбери хотя бы один день недели'}).first().waitFor();
  assert.equal(posts.filter(p=>p.action==='onboarding').length,0,'Legacy/new blank weekdays must not be submitted');
  for(const day of [0,2,4])await onboarding.locator('[data-onboard-weekday="'+day+'"]').click();
  await onboarding.locator('[data-onboard-weekday="0"]').focus();
  await onboarding.keyboard.press('Space');
  assert.equal(await onboarding.locator('[data-onboard-weekday="0"]').getAttribute('aria-pressed'),'false');
  await onboarding.keyboard.press('Space');
  assert.equal(await onboarding.locator('[data-onboard-weekday="0"]').getAttribute('aria-pressed'),'true','Keyboard focus survives weekday toggle');
   await onboarding.getByRole('button',{name:'Сохранить анкету',exact:true}).click();
   await onboarding.waitForFunction(()=>/Доброе утро|Добрый день|Добрый вечер|Доброй ночи/.test(document.querySelector('h1')?.textContent||''));
  assert.deepEqual(posts.find(p=>p.action==='onboarding').answers.weekdays,[0,2,4]);
  assert.equal(posts.find(p=>p.action==='onboarding').answers.days,'3');
  assert.equal(posts.find(p=>p.action==='onboarding').metrics.sex,'female');
   assert.equal(posts.find(p=>p.action==='onboarding').metrics.birth_date,'1992-10-20','Full DOB used instead of old age field');
  assert.equal(posts.find(p=>p.action==='onboarding').answers.minutes,'120');
  assert.equal(await onboarding.locator('body.theme-female').count(),1,'Pink theme persists after save');
  assert.equal(await onboarding.locator('.bottom-nav button').count(),3,'Three tabs after onboarding save');
  await onboarding.getByRole('button',{name:'Профиль',exact:true}).click();
  await onboarding.getByText('Профиль:',{exact:true}).waitFor();
   assert.equal(await onboarding.getByRole('button',{name:'Редактировать анкету'}).count(),0);
  for(const day of [0,2,4])assert.equal(await onboarding.locator('[data-onboard-weekday="'+day+'"]').getAttribute('aria-pressed'),'true','Saved weekday restored');
  await onboarding.screenshot({path:path.join(OUT,'saved-weekdays.png')});
  await onboarding.getByText('Женский календарь',{exact:true}).waitFor();
   await onboarding.locator('.bottom-nav [data-nav="progress"]').click();
   assert.equal(await onboarding.getByText('Женский календарь',{exact:true}).count(),0);
   await onboarding.getByRole('button',{name:'Профиль',exact:true}).click();
   await onboarding.getByText('Женский календарь',{exact:true}).waitFor();
  await onboarding.locator('#period-start').fill('2026-09-01');
  await onboarding.locator('#period-end').fill('2026-09-05');
  await onboarding.getByRole('button',{name:'Добавить период'}).click();
  await onboarding.getByText('01.09.2026 — 05.09.2026',{exact:true}).waitFor();
  assert.equal(await onboarding.locator('.fq-cycle-day.recorded').count(),5,'Only actual period days highlighted');
  assert.equal(await onboarding.locator('.fq-cycle-month [role="columnheader"]').count(),7);
  await onboarding.getByRole('button',{name:'Предыдущий месяц'}).click();
  assert.equal(await onboarding.locator('.fq-cycle-day.recorded').count(),0,'August has no false highlights');
  await onboarding.getByRole('button',{name:'Следующий месяц'}).click();
  assert.equal(await onboarding.locator('.fq-cycle-day.recorded').count(),5,'Saved days restored on September');
  await onboarding.getByRole('button',{name:'Изменить',exact:true}).click();
  await onboarding.locator('#period-end').fill('2026-09-06');
  await onboarding.getByRole('button',{name:'Сохранить исправление'}).click();
  await onboarding.getByText('01.09.2026 — 06.09.2026',{exact:true}).waitFor();
  assert.equal(await onboarding.locator('.fq-cycle-day.recorded').count(),6,'Edit repaints observed days');
  await onboarding.screenshot({path:path.join(OUT,'female-period-calendar.png')});
  const deletions=posts.filter(p=>p.action==='period_delete').length;
  await onboarding.getByRole('button',{name:'Удалить',exact:true}).click();
  assert.equal(posts.filter(p=>p.action==='period_delete').length,deletions,'No deletion without confirmation');
  await onboarding.getByRole('button',{name:'Отмена',exact:true}).click();
  assert.equal(await onboarding.locator('.fq-cycle-day.recorded').count(),6,'Cancellation preserves history');
  await onboarding.getByRole('button',{name:'Удалить',exact:true}).click();
  await onboarding.getByRole('button',{name:'Удалить запись'}).click();
  await onboarding.getByText('Записей пока нет.',{exact:true}).waitFor();
  assert.equal(await onboarding.locator('.fq-cycle-day.recorded').count(),0);
  assert.equal(posts.filter(p=>p.action==='period_delete').length,deletions+1);
  await onboarding.close();
  process.stdout.write('PASS browser: 3 tabs, nested plan, screen layout, fullscreen stub, profile, first launch (2 mobile sizes)\n');
 }finally{
  if(browser)await browser.close();
  await new Promise(resolve=>server.close(resolve));
 }
}
run().catch(e=>{console.error(e);process.exitCode=1});
