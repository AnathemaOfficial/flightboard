// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('  // ---- optional advisor:'), end = source.indexOf('  // ---- end optional advisor', start);
assert.ok(start >= 0 && end > start, 'execute the actual optional adviser code');
class Element {
  constructor(id) { this.id=id; this.value=''; this.checked=false; this.disabled=false; this.hidden=false; this.textContent=''; this.listeners=new Map(); }
  addEventListener(name, fn) { if(!this.listeners.has(name)) this.listeners.set(name,[]); this.listeners.get(name).push(fn); }
  fire(name, event={isTrusted:true}) { return Promise.all((this.listeners.get(name)||[]).map(fn=>fn(event))); }
}
function fixture({live=true, token='local-test-token'}={}) {
  const nodes=new Map();
  for(const id of source.matchAll(/\bid="(advisor[^" ]*)"/g)) nodes.set(id[1],new Element(id[1]));
  const $=id=>{assert.ok(nodes.has(id),'known adviser node '+id);return nodes.get(id);};
  $('advisor').hidden=true;
  $('advisor-protocol').value='openai';$('advisor-max-output').value='1024';
  $('advisor-interval').value='60';$('advisor-max-calls').value='4';
  const events=new Map(), windowEvents=new Map(), timers=new Map(), calls=[], replies=[];
  let timerId=0;
  const document={hidden:false,querySelector:selector=>{assert.equal(selector,'meta[name="flightboard-advisor-token"]');return {content:token};},
    addEventListener:(name,fn)=>{if(!events.has(name))events.set(name,[]);events.get(name).push(fn);}};
  const context={$,polling:live,document,window:{addEventListener:(name,fn)=>windowEvents.set(name,fn)},
    t:(key,args={})=>key+(Object.keys(args).length?' '+JSON.stringify(args):''),AbortController,
    setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>timers.delete(id),
    fetch:async(path,options)=>{calls.push({path,options,body:options.body?JSON.parse(options.body):undefined});
      assert.ok(replies.length,'a deliberate fake response is required');return await replies.shift()(path,options);}};
  vm.runInNewContext(source.slice(start,end)+'\nthis.api={advisor,advisorInit,advisorControls,advisorInvalidate,advisorPrepare,advisorSend,advisorPoll,advisorRevoke};',context);
  const reply=value=>replies.push(async()=>({ok:true,json:async()=>value}));
  const input=async(id,value)=>{if(typeof value==='boolean')$(id).checked=value;else $(id).value=value;await $(id).fire('input');};
  const ready=async()=>{await input('advisor-model','test-model');await input('advisor-consent-board',true);};
  const preview=()=>({state:'prepared',preview:{id:'preview-one',sha256:'a'.repeat(64),
    config:{protocol:'openai',endpoint:'https://api.openai.com/v1',model:'test-model',max_output_tokens:1024},
    question:'question',context:{board:{generated_at:'2026-11-21T20:00:00-05:00'},
      files:[{source:'repo:architecture.md',text:'Selected text'}],omitted:[{source:'repo:.env',reason:'secret_file'}]},
    created_at:'2026-11-21T20:00:00-05:00',expires_at:'2026-11-21T20:10:00-05:00',bytes:432}});
  const prepare=async()=>{reply(preview());await $('advisor-prepare').fire('click');};
  context.api.advisorInit();
  return {$,context,calls,replies,reply,input,ready,prepare,preview,events,windowEvents,timers};
}
async function checks() {
  for(const options of [{live:false},{token:''},{token:'__FLIGHTBOARD_ADVISOR_TOKEN__'}]) {
    const f=fixture(options);assert.equal(f.$('advisor').hidden,true);assert.equal(f.calls.length,0);
  }
  const authorization={config:{protocol:'anthropic',endpoint:'https://custom.example/v1',model:'nondefault-model',max_output_tokens:2048},
    question:'Compare architecture with the local evidence.',repo_files:['docs/architecture.md'],local_files:['/tmp/evidence/nondefault.json']};
  const restored=fixture();assert.match(restored.$('advisor-status').textContent,/advisor_state_unchecked/);
  restored.reply({state:'complete',authorization,automatic:{enabled:true,used:2,max_calls:4,remaining:2,interval_minutes:90,next_check_at:'next',expires_at:'expiry'},
    result:{text:'Existing authorized follow-up',usage:{},elapsed_seconds:1}});
  restored.$('advisor').open=true;await restored.$('advisor').fire('toggle');
  assert.equal(restored.calls.length,1);assert.equal(restored.calls[0].path,'advisor/status');
  assert.equal(restored.$('advisor-config').disabled,true);assert.match(restored.$('advisor-status').textContent,/advisor_automatic_status/);
  assert.equal(restored.$('advisor-result').textContent,'Existing authorized follow-up','opening a newly loaded page restores existing status');
  assert.equal(restored.$('advisor-protocol').value,'anthropic');assert.equal(restored.$('advisor-endpoint').value,'https://custom.example/v1');
  assert.equal(restored.$('advisor-model').value,'nondefault-model');assert.equal(restored.$('advisor-max-output').value,'2048');
  assert.equal(restored.$('advisor-question').value,authorization.question);assert.equal(restored.$('advisor-interval').value,'90');
  assert.equal(restored.$('advisor-repo-files').value,'docs/architecture.md');assert.equal(restored.$('advisor-local-files').value,'/tmp/evidence/nondefault.json');
  assert.equal(restored.$('advisor-key').value,'');assert.equal(restored.$('advisor-authorized-scope').hidden,false);
  assert.match(restored.$('advisor-authorized-scope').textContent,/nondefault-model/);assert.match(restored.$('advisor-authorized-scope').textContent,/nondefault.json/);
  restored.reply({state:'revoked'});await restored.$('advisor-revoke').fire('click');assert.equal(restored.context.api.advisor.automatic,null);
  const expired=fixture();expired.reply({state:'expired',automatic:{enabled:false}});
  expired.$('advisor').open=true;await expired.$('advisor').fire('toggle');
  assert.match(expired.$('advisor-status').textContent,/advisor_state_expired/);
  assert.equal(expired.context.api.advisor.uncertain,false);assert.equal(expired.$('advisor-config').disabled,false);
  await expired.ready();await expired.prepare();await expired.input('advisor-consent-send',true);
  assert.equal(expired.$('advisor-send').disabled,false);
  expired.reply({state:'expired',automatic:{enabled:false}});await expired.context.api.advisorPoll(true);
  await expired.input('advisor-consent-send',true);
  assert.equal(expired.context.api.advisor.preview,null);assert.equal(expired.$('advisor-send').disabled,true);
  const unknown=fixture();unknown.replies.push(async()=>{throw new Error('status unavailable');});
  unknown.$('advisor').open=true;await unknown.$('advisor').fire('toggle');
  assert.equal(unknown.context.api.advisor.uncertain,true);assert.equal(unknown.$('advisor-config').disabled,true);
  assert.match(unknown.$('advisor-status').textContent,/advisor_status_failed/);
  unknown.reply({state:'disabled',automatic:{enabled:false}});await unknown.context.api.advisorPoll();
  assert.equal(unknown.context.api.advisor.uncertain,false);assert.equal(unknown.$('advisor-config').disabled,false);
  const f=fixture(), {$,context,calls}=f;
  assert.equal($('advisor').hidden,false);assert.equal(calls.length,0);assert.equal(f.timers.size,0);
  assert.equal($('advisor-prepare').disabled,true);assert.equal($('advisor-send').disabled,true);
  await f.ready();assert.equal($('advisor-prepare').disabled,false);
  await f.input('advisor-repo-files','architecture.md');assert.equal($('advisor-prepare').disabled,true);
  await f.input('advisor-consent-repo',true);assert.equal($('advisor-prepare').disabled,false);
  await f.input('advisor-local-files','/tmp/evidence/receipt.json');assert.equal($('advisor-prepare').disabled,true);
  await f.input('advisor-consent-local',true);assert.equal($('advisor-prepare').disabled,false);
  await $('advisor-prepare').fire('click',{isTrusted:false});assert.equal(calls.length,0,'synthetic clicks cannot prepare files');
  await f.prepare();assert.equal(calls.length,1);assert.equal(calls[0].path,'advisor/preview');
  assert.deepEqual(calls[0].body.repo_files,['architecture.md']);assert.deepEqual(calls[0].body.local_files,['/tmp/evidence/receipt.json']);
  assert.equal(calls[0].body.consent_board,true);assert.equal(calls[0].body.consent_repo,true);assert.equal(calls[0].body.consent_local,true);
  assert.equal(Object.hasOwn(calls[0].body,'api_key'),false);assert.equal($('advisor-preview-section').hidden,false);
  assert.deepEqual(JSON.parse($('advisor-preview').value),{question:'question',context:f.preview().preview.context});
  assert.match($('advisor-preview-meta').textContent,/test-model/);assert.match($('advisor-preview-meta').textContent,/api.openai.com/);
  assert.equal($('advisor-send').disabled,true,'local reading consent never authorizes external sharing');
  assert.equal(calls[0].options.headers['X-Flightboard-Advisor'],'local-test-token');
  assert.equal(calls[0].options.headers['Content-Type'],'application/json');
  assert.equal(calls[0].options.redirect,'error');assert.equal(calls[0].options.credentials,'same-origin');

  $('advisor-key').value='FAKE-TEST-KEY';await f.input('advisor-consent-send',true);
  assert.equal($('advisor-send').disabled,false);
  await f.input('advisor-question','Changed question');
  assert.equal(context.api.advisor.preview,null);assert.equal($('advisor-send').disabled,true);
  assert.equal($('advisor-key').value,'');assert.equal($('advisor-consent-send').checked,false);
  assert.equal($('advisor-preview-section').hidden,true);

  let releasePreview;
  f.replies.push(()=>new Promise(resolve=>{releasePreview=()=>resolve({ok:true,json:async()=>f.preview()});}));
  const pending=$('advisor-prepare').fire('click');await Promise.resolve();
  await f.input('advisor-model','new-model');releasePreview();await pending;
  assert.equal(context.api.advisor.preview,null,'a late preview cannot restore an obsolete scope');
  assert.equal($('advisor-send').disabled,true);

  await f.input('advisor-model','test-model');await f.prepare();await f.input('advisor-consent-send',true);
  $('advisor-key').value='FAKE-TEST-KEY';
  f.reply({state:'running',job_id:'job-one'});
  const sending=$('advisor-send').fire('click');assert.equal($('advisor-key').value,'','clear the field before awaiting network');
  await sending;assert.equal(calls.at(-1).path,'advisor/analyze');assert.equal(calls.at(-1).body.api_key,'FAKE-TEST-KEY');
  assert.equal(calls.at(-1).body.preview_id,'preview-one');assert.equal(calls.at(-1).body.consent_send,true);
  assert.equal(context.api.advisor.preview,null,'a submitted preview cannot be reused for another authorization');
  assert.equal($('advisor-config').disabled,true);assert.equal(context.api.advisor.running,true);
  f.context.document.hidden=true;const beforeHidden=calls.length;await context.api.advisorPoll();assert.equal(calls.length,beforeHidden);
  f.context.document.hidden=false;for(const fn of f.events.get('visibilitychange'))fn();
  assert.ok([...f.timers.values()].some(timer=>timer.delay===0),'returning to the tab resumes status checks only');
  const hostile='</pre><img src=x onerror=alert(1)> No implementation evidence.';
  f.reply({state:'complete',result:{text:hostile,usage:{input_tokens:42},elapsed_seconds:1.5}});
  await context.api.advisorPoll();assert.equal($('advisor-result').textContent,hostile);
  assert.equal($('advisor-result-section').hidden,false);assert.match($('advisor-result-meta').textContent,/42/);
  assert.match($('advisor-result-meta').textContent,/advisor_unknown/);assert.equal($('advisor-config').disabled,false);
  assert.equal(f.timers.size,0,'a completed one-off analysis does not keep polling');

  await f.input('advisor-consent-send',true);await f.input('advisor-consent-automatic',true);
  const consumedCalls=calls.length;await $('advisor-automate').fire('click');assert.equal(calls.length,consumedCalls,'a consumed preview cannot authorize automatic calls');
  assert.equal($('advisor-send').disabled,true);assert.equal($('advisor-automate').disabled,true);
  await f.prepare();await f.input('advisor-consent-send',true);await f.input('advisor-consent-automatic',true);
  await f.input('advisor-interval','14');assert.equal($('advisor-automate').disabled,true);
  await f.input('advisor-interval','60');await f.input('advisor-max-calls','21');assert.equal($('advisor-automate').disabled,true);
  await f.input('advisor-max-calls','4');assert.equal($('advisor-automate').disabled,false);
  $('advisor-key').value='FAKE-AUTO-KEY';
  f.reply({state:'running',job_id:'job-auto',automatic:{enabled:true,used:1,max_calls:4,remaining:3,interval_minutes:60}});
  await $('advisor-automate').fire('click');assert.equal(calls.at(-1).path,'advisor/automate');
  assert.equal(calls.at(-1).body.consent_automatic,true);assert.equal(calls.at(-1).body.max_calls,4);
  assert.equal(calls.at(-1).body.interval_minutes,60);assert.equal($('advisor-key').value,'');
  f.reply({state:'complete',automatic:{enabled:true,used:1,max_calls:4,remaining:3,next_check_at:'next',expires_at:'expiry'},
    result:{text:'Frozen automatic result',usage:{input_tokens:10,output_tokens:20},elapsed_seconds:1}});
  await context.api.advisorPoll();assert.equal($('advisor-config').disabled,true,'an automatic grant locks its configured scope');
  assert.match($('advisor-status').textContent,/advisor_automatic_status/);
  assert.ok([...f.timers.values()].some(timer=>timer.delay===30000),'scheduled follow-up uses slow status-only polling');
  f.reply({state:'complete',automatic:{enabled:true,used:1,max_calls:4,remaining:3,next_check_at:'next',expires_at:'expiry'},
    error:'automatic_context_unavailable',result:{text:'Frozen automatic result',usage:{input_tokens:10,output_tokens:20},elapsed_seconds:1}});
  await context.api.advisorPoll();assert.match($('advisor-status').textContent,/advisor_automatic_context_unavailable/);
  assert.doesNotMatch($('advisor-status').textContent,/advisor_state_error/,'a skipped context read is not a failed paid provider attempt');
  assert.equal($('advisor-result').textContent,'Frozen automatic result','the older point-in-time result remains visibly scoped');
  f.reply({state:'error',automatic:{enabled:true,used:1,max_calls:4,remaining:3,next_check_at:'next',expires_at:'expiry'},
    error:'automatic_context_unavailable'});
  await context.api.advisorPoll();assert.match($('advisor-status').textContent,/advisor_automatic_context_unavailable/);
  assert.doesNotMatch($('advisor-status').textContent,/advisor_state_error/);
  f.reply({state:'revoked'});await $('advisor-revoke').fire('click');
  assert.equal(calls.at(-1).path,'advisor/revoke');assert.equal($('advisor-config').disabled,false);
  assert.equal($('advisor-result').textContent,'');assert.equal(context.api.advisor.preview,null);
  assert.equal(context.api.advisor.automatic,null);assert.equal(f.timers.size,0);

  await f.prepare();await f.input('advisor-consent-send',true);$('advisor-key').value='FAKE-RACE-KEY';
  let releaseSend;
  f.replies.push(()=>new Promise(resolve=>{releaseSend=()=>resolve({ok:true,json:async()=>({state:'running',job_id:'late-job'})});}));
  const late=$('advisor-send').fire('click');await Promise.resolve();
  f.reply({state:'revoked'});await $('advisor-revoke').fire('click');releaseSend();await late;
  assert.equal(context.api.advisor.running,false,'late analysis response cannot restart polling after revocation');
  assert.equal(context.api.advisor.preview,null);assert.equal(f.timers.size,0);
  f.windowEvents.get('pagehide')();assert.equal($('advisor-key').value,'');
  for(const automatic of [false,true]) {
    const uncertain=fixture();await uncertain.ready();await uncertain.prepare();await uncertain.input('advisor-consent-send',true);
    if(automatic) await uncertain.input('advisor-consent-automatic',true);
    uncertain.$('advisor-key').value='FAKE-UNCERTAIN-KEY';
    uncertain.replies.push(async()=>{throw new Error('accepted response lost');});
    await uncertain.$(automatic?'advisor-automate':'advisor-send').fire('click');
    assert.equal(uncertain.context.api.advisor.uncertain,true);assert.equal(uncertain.$('advisor-config').disabled,true);
    assert.equal(uncertain.$('advisor-key').value,'');assert.equal(uncertain.context.api.advisor.preview,null);
    assert.match(uncertain.$('advisor-status').textContent,/advisor_send_uncertain/);
    const reconciliation=[...uncertain.timers.values()].find(timer=>timer.delay===0);assert.ok(reconciliation);
    uncertain.reply(automatic ? {state:'complete',authorization,
      automatic:{enabled:true,used:1,max_calls:4,remaining:3,interval_minutes:60,next_check_at:'next',expires_at:'expiry'}}
      : {state:'running',job_id:'accepted-manual'});
    await reconciliation.fn();assert.equal(uncertain.context.api.advisor.uncertain,false);
    assert.equal(uncertain.calls.at(-1).path,'advisor/status');assert.equal(uncertain.$('advisor-config').disabled,true);
    assert.equal(uncertain.calls.filter(call=>['advisor/analyze','advisor/automate'].includes(call.path)).length,1,
      'reconciling an ambiguous accepted send never retries the provider request');
    uncertain.reply({state:'revoked'});await uncertain.$('advisor-revoke').fire('click');
  }
  assert.ok(calls.every(call=>call.path.startsWith('advisor/')),'the panel never refreshes or reloads the board');
  console.log('19 adviser-page checks passed');
}
checks().catch(error=>{console.error(error);process.exitCode=1;});
