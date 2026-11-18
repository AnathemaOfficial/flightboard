// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const between = (first, last) => source.slice(source.indexOf(first), source.indexOf(last, source.indexOf(first)));
const code = [between('  function renderTask(id)', '  function openTask(id)'),
  between('  function completedAt(', '  let lastOk = '),
  between('  function renderHeader()', '  function renderLive()'),
  between('  function renderLive()', '  // ---- what waits'),
  between('  function observedStamp(value)', '  function card(c)'),
  between('  function renderFooter()', '  function draw('),
  source.split('\n').find(line => line.startsWith('  const render = ')),
  between('  function requestTimeout()', '  let resizing')].join('\n');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const checks = new AsyncFunction('assert', `
  const nodes = new Map();
  const $ = id => { if (!nodes.has(id)) nodes.set(id, {id, textContent:'', className:'', children:[]}); return nodes.get(id); };
  ${source.split('\n').find(line => line.startsWith('  const own = '))}
  const h = (tag, props, ...children) => ({tag, props, children});
  const put = (node, ...children) => {
    node.children = children;
    const visible=children.flat(Infinity).filter(value=>value!==null && value!==undefined && value!==false);
    node.textContent=visible.length?JSON.stringify(visible):'';
  };
  const t = (key, values={}) => key + (Object.keys(values).length ? ' ' + JSON.stringify(values) : '');
  const tn = (key, n, values={}) => t(key,{n,...values});
  const label = (group, value) => value;
  const statusName = value => value;
  const statusDot = value => value;
  const mainSide = task => task.status_main || '';
  const stamp = value => value;
  const ago = value => value;
  const when = value => Date.parse(value);
  const live = value => value;
  const tracked = () => true;
  const document = {hidden:false, body:{classList:{toggle:(key, on) => { document.stale = on; }}}};
  const timers = new Map(); let timerId = 0;
  const setTimeout = (fn, delay) => { timers.set(++timerId,{fn,delay}); return timerId; };
  const clearTimeout = id => timers.delete(id);
  const polling = true;
  let timer=0, refreshVersion=0, refreshController=null, failed='', lost=false, lastKey='';
  const task = (title, status) => ({title,status,status_main:status,milestone:'M1',owner:'codex',priority:'P1',release:'',acceptance:['Works'],dependencies:[],waiting_on:[]});
  const state = (title='old',status='planned',seconds=12) => ({generated_at:'2026-11-17T21:00:00-05:00',
    main:{state:'ok',ref:'main',head:'123abcd',date:'2026-11-17T20:00:00-05:00',subject:'fixture',valid:true},
    repository:'fixture',resume:'read',sources:[{key:'git',label:'Git',state:'ok',detail:''}],
    sessions:[],waiting:[],tasks:{'T-1':task(title,status)},refresh_seconds:10,settings:{read_seconds:seconds}});
  let data=state(), openedTask='T-1', fetch;
  ${source.split('\n').find(line => line.startsWith('  let lastOk = '))}
  const redraw = fn => fn();
  const renderStatic=()=>{}, renderNext=()=>{}, renderEvents=()=>{}, renderKpis=()=>{}, renderScope=()=>{}, renderCharts=()=>{};
  const renderSessions=()=>{ put($('sessions'), data.sessions.map(trackingCard)); };
  const renderWaiting=()=>{ $('waiting').textContent=JSON.stringify(data.waiting); };
  const keyOf = text => text.replace(/^\\{"generated_at":"[^"]*",/, '{');
  ${code}
  const response = next => ({ok:true,text:async()=>JSON.stringify(next)});
  assert.equal(lastOk,Date.parse(data.generated_at),'initial success time belongs to the completed snapshot');

  const observed = (kind='check', reason='settled') => ({last_write:'2026-11-17T20:00:00-05:00',
    file_activity_observed_at:'2026-11-17T20:00:00-05:00',file_activity_complete:true,
    file_activity_partial_reasons:[],ledger_file_modified_at:'2026-11-15T18:00:00-05:00',
    tracking:{state:kind,reason}});
  const described = trackingCard(observed());
  assert.match(JSON.stringify(described),/2026-11-17T20:00/);
  assert.match(JSON.stringify(described),/2026-11-15T18:00/);
  assert.match(JSON.stringify(described),/page.tracking_check/);
  assert.match(JSON.stringify(trackingCard(observed('info','ongoing'))),/page.tracking_info/);
  assert.match(JSON.stringify(trackingCard(observed('unknown','partial'))),/page.tracking_unknown/);
  const noSignal=JSON.stringify(trackingCard(observed('none','')));
  assert.doesNotMatch(noSignal,/page.tracking_(check|info|unknown)/);
  const hostileDate=trackingCard({...observed(),file_activity_observed_at:'<img src=x onerror=alert(1)>'});
  assert.doesNotMatch(JSON.stringify(hostileDate),/onerror/);
  assert.match(JSON.stringify(hostileDate),/page.date_unknown/);
  assert.doesNotMatch(JSON.stringify(trackingCard(observed('check','<script>'))),/<script>/);
  assert.doesNotThrow(()=>trackingCard(observed('check',{toString:'not callable'})));
  assert.doesNotThrow(()=>trackingCard({...observed(),file_activity_observed_at:{toString:()=>{throw new Error('coerced date');}}}));
  const directoryOnly=JSON.stringify(trackingCard({...observed(),file_activity_observed_at:''}));
  assert.doesNotMatch(directoryOnly,/2026-11-17T20:00/);
  assert.match(directoryOnly,/page.date_unknown/);
  const partialCard={...observed(),file_activity_complete:false,file_activity_partial_reasons:['limit','depth']};
  const partialText=JSON.stringify(trackingCard(partialCard));
  assert.match(partialText,/page.tracking_check/);
  assert.match(partialText,/page.tracking_partial_note/);
  assert.match(partialText,/page.tracking_partial_limit/);
  assert.match(partialText,/page.tracking_partial_depth/);
  const hostileReasons=['<script>',{toString:()=>{throw new Error('coerced reason');}},['limit'],'__proto__','limit'];
  let safePartial;
  assert.doesNotThrow(()=>{safePartial=JSON.stringify(trackingCard({...partialCard,file_activity_partial_reasons:hostileReasons}));});
  assert.doesNotMatch(safePartial,/<script>|__proto__/);
  assert.match(safePartial,/page.tracking_partial_limit/);
  for (const reasons of ['limit',null,{toString:()=>{throw new Error('coerced list');}}]) {
    assert.doesNotThrow(()=>trackingCard({...partialCard,file_activity_partial_reasons:reasons}));
  }
  for (const kind of ['branch','remote']) {
    const ref={...observed('none',''),kind,file_activity_complete:false,
      file_activity_partial_reasons:['unreadable'],file_activity_observed_at:'',ledger_file_modified_at:''};
    assert.equal(trackingCard(ref),null,'healthy refs have no local-file observation warning');
    const refused={...ref,kind:'worktree',reason:'outside',files_read:false,
      tracking:{state:'unknown',reason:'unreadable'}};
    assert.match(JSON.stringify(trackingCard(refused)),/page.tracking_unknown/);
    assert.match(JSON.stringify(trackingCard(refused)),/page.tracking_partial_unreadable/);
    const brokenRef={...ref,reason:'read_failed',tracking:{state:'unknown',reason:'unreadable'}};
    assert.match(JSON.stringify(trackingCard(brokenRef)),/page.tracking_unknown/);
  }

  assert.equal(requestTimeout(),20000);
  for (const [seconds,expected] of [[12,20000],[30,38000],[120,128000]]) {
    data=state('old','planned',seconds); assert.equal(requestTimeout(),expected);
  }
  const hostile='</script><img src=x onerror=alert(1)>';
  for (const seconds of [11,121,null,'30',30.5,hostile,{valueOf:()=>{throw new Error('budget coerced');}}]) {
    data=state('old','planned',seconds); assert.equal(requestTimeout(),20000);
  }
  delete data.settings; assert.equal(requestTimeout(),20000);
  data=state();
  render();
  assert.match($('task-body').textContent,/old/);
  fetch=async()=>response(state('new title','done'));
  await refresh();
  assert.match($('task-body').textContent,/new title/);
  assert.match($('task-body').textContent,/done/);
  data.tasks['T-1'].conflict=true; data.tasks['T-1'].status_main=null; render();
  assert.match($('task-body').textContent,/page.task_conflict/);
  assert.doesNotMatch($('task-body').textContent,/done/);

  const missing=state(); missing.tasks={}; fetch=async()=>response(missing);
  await refresh();
  assert.match($('task-body').textContent,/page.task_unavailable/);
  assert.doesNotMatch($('task-body').textContent,/new title/);

  data=state(); data.waiting=[{verb:'Give your merge go'}];
  const unread=state(); unread.main={state:'unreadable',reason_text:'unavailable'}; unread.tasks={};
  fetch=async()=>response(unread); await refresh();
  assert.equal(data.main.state,'unreadable'); assert.deepEqual(data.waiting,[]);
  assert.equal($('live').className,'live failed');
  assert.equal($('live-state').textContent,'page.spoken_failed');

  const pending=[];
  fetch=()=>new Promise(resolve=>pending.push(resolve));
  const first=refresh(); const second=refresh();
  pending[1](response(state('latest','done'))); await second;
  pending[0](response(state('late old response','planned'))); await first;
  assert.equal(data.tasks['T-1'].title,'latest');

  fetch=async(url, options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('aborted'))));
  const stalled=refresh();
  const timeout=Array.from(timers.values()).find(entry=>entry.delay===20000);
  assert.ok(timeout); timeout.fn(); await stalled;
  assert.equal(lost,true); assert.equal($('live').className,'live lost');
  assert.match($('task-body').textContent,/page.task_unavailable/);
  assert.match($('waiting').textContent,/page.nothing_readable/);
  assert.equal($('progress').hidden,true);

  const good=state('recovered','done'); fetch=async()=>response(good); await refresh();
  assert.equal(lost,false); assert.equal(failed,''); assert.equal($('live').className,'live on');
  assert.equal($('banner').textContent,'');

  // Observation dates and notices are replaced by refreshed data and cleared on a failed refresh.
  const dated=state(); dated.generated_at='2026-11-17T21:00:00-05:00'; dated.sessions=[observed()];
  fetch=async()=>response(dated); await refresh();
  assert.equal(lastOk,Date.parse(dated.generated_at),'cached success keeps its observation time');
  assert.match($('reading').textContent,/2026-11-17T21:00/);
  assert.match($('sessions').textContent,/page.tracking_check/);
  assert.match($('sessions').textContent,/2026-11-15T18:00/);
  const partialReading={...dated,sessions:[partialCard]};
  fetch=async()=>response(partialReading); await refresh();
  assert.match($('sessions').textContent,/page.tracking_partial_note/);
  assert.match($('sessions').textContent,/page.tracking_partial_limit/);
  fetch=async()=>response(dated); await refresh();
  assert.doesNotMatch($('sessions').textContent,/page.tracking_partial_note/);
  const nextReading={...dated,generated_at:'2026-11-17T21:00:10-05:00'};
  fetch=async()=>response(nextReading); await refresh();
  assert.match($('reading').textContent,/2026-11-17T21:00:10/);
  fetch=async()=>{throw new Error('connection lost');}; await refresh();
  assert.match($('banner').textContent,/2026-11-18T02:00:10.000Z/);
  assert.equal($('reading').textContent,'');
  assert.doesNotMatch($('sessions').textContent,/page.tracking_check|2026-11-15T18:00/);
  fetch=async()=>response(nextReading); await refresh();
  assert.match($('sessions').textContent,/page.tracking_check/);
  assert.match($('reading').textContent,/2026-11-17T21:00:10/);
  lost=true; $('banner').textContent='old error'; fetch=async()=>response(good); await refresh();
  assert.equal($('banner').textContent,'');

  // A configured budget survives server errors and transport timeouts, then follows the recovered settings.
  const configured=state('configured','planned',30); data=configured;
  const configuredError=state('failed','planned',30);
  configuredError.main={state:'unreadable',reason_text:'unavailable'};
  fetch=async()=>response(configuredError); await refresh();
  assert.equal(requestTimeout(),38000);
  fetch=async(url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('aborted'))));
  const configuredStalled=refresh();
  const configuredTimeout=Array.from(timers.values()).find(entry=>entry.delay===38000);
  assert.ok(configuredTimeout); configuredTimeout.fn(); await configuredStalled;
  assert.equal(lost,true); assert.equal(requestTimeout(),38000);
  fetch=async()=>response(state('recovered','done',120)); await refresh();
  assert.equal(lost,false); assert.equal(failed,''); assert.equal(requestTimeout(),128000);

  // The first HTML shell is neutral and fetches immediately with its known large-repository deadline.
  data=state('loading','planned',120); data.main={state:'loading',reason_text:''};
  data.tasks={}; data.waiting=[]; lastOk=null; failed=''; lost=false; openedTask=null;
  render();
  assert.equal($('live').className,'live loading');
  assert.equal($('live-state').textContent,'page.spoken_loading');
  assert.equal(document.stale,false);
  let immediateCalls=0, finishInitial;
  const existingTimers=new Set(timers.keys());
  fetch=()=>{immediateCalls++;return new Promise(resolve=>{finishInitial=resolve;});};
  const initialRequest=startPolling();
  assert.equal(immediateCalls,1);
  assert.equal(data.main.state,'loading');
  const initialTimers=()=>Array.from(timers).filter(([id])=>!existingTimers.has(id)).map(([,entry])=>entry.delay);
  assert.deepEqual(initialTimers(),[128000]);
  finishInitial(response(state('first result','done',120))); await initialRequest;
  assert.deepEqual(initialTimers(),[10000]);
  assert.equal(data.main.state,'ok'); assert.equal($('live').className,'live on');
  assert.notEqual(lastOk,null); assert.equal(requestTimeout(),128000);

  // An initial failure does not pretend that any repository data was read successfully.
  data=state('loading','planned',120); data.main={state:'loading',reason_text:''};
  data.sources=[{key:'git',label:'Git',state:'loading',detail:'loading reading'}];
  data.tasks={}; data.waiting=[]; lastOk=null; failed=''; lost=false;
  render();
  fetch=async()=>{throw new Error('initial transport failure');};
  await startPolling();
  assert.equal(lastOk,null); assert.equal(lost,true);
  assert.equal($('live').className,'live lost');
  assert.match($('banner').textContent,/page.initial_failed/);
  assert.match($('snapshot').textContent,/page.unreadable/);
  assert.doesNotMatch($('snapshot').textContent,/page.loading/);
  assert.match($('footer').textContent,/unreadable/);
  assert.doesNotMatch($('footer').textContent,/loading/);
  fetch=async()=>response(state('eventual result','done',120)); await refresh();
  assert.equal(lost,false); assert.equal(failed,''); assert.equal($('live').className,'live on');

  document.hidden=true; let calls=0; fetch=async()=>{calls++;return response(state());}; await refresh();
  assert.equal(calls,0);
  return '14 live-page checks passed';
`);
checks(assert).then(result => console.log(result)).catch(error => { console.error(error); process.exitCode=1; });
