// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const between = (first, last) => source.slice(source.indexOf(first), source.indexOf(last, source.indexOf(first)));
const code = [between('  function renderTask(id)', '  function openTask(id)'),
  between('  function renderLive()', '  // ---- what waits'),
  source.split('\n').find(line => line.startsWith('  const render = ')),
  between('  async function refresh()', '  let resizing')].join('\n');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const checks = new AsyncFunction('assert', `
  const nodes = new Map();
  const $ = id => { if (!nodes.has(id)) nodes.set(id, {id, textContent:'', className:'', children:[]}); return nodes.get(id); };
  const own = (obj, key) => Object.hasOwn(obj, key) ? obj[key] : undefined;
  const h = (tag, props, ...children) => ({tag, props, children});
  const put = (node, ...children) => { node.children = children; node.textContent = JSON.stringify(children); };
  const t = key => key;
  const label = (group, value) => value;
  const statusName = value => value;
  const statusDot = value => value;
  const mainSide = task => task.status_main || '';
  const stamp = value => value;
  const ago = value => value;
  const when = value => Date.parse(value);
  const document = {hidden:false, body:{classList:{toggle:(key, on) => { document.stale = on; }}}};
  const timers = new Map(); let timerId = 0;
  const setTimeout = (fn, delay) => { timers.set(++timerId,{fn,delay}); return timerId; };
  const clearTimeout = id => timers.delete(id);
  const polling = true;
  const REQUEST_TIMEOUT_MS = 20000;
  let timer=0, refreshVersion=0, refreshController=null, failed='', lost=false, lastOk=Date.now(), lastKey='';
  const task = (title, status) => ({title,status,status_main:status,milestone:'M1',owner:'codex',priority:'P1',release:'',acceptance:['Works'],dependencies:[],waiting_on:[]});
  const state = (title='old',status='planned') => ({generated_at:new Date().toISOString(),main:{state:'ok'},sessions:[],waiting:[],tasks:{'T-1':task(title,status)},refresh_seconds:10});
  let data=state(), openedTask='T-1', fetch;
  const redraw = fn => fn();
  const renderStatic=()=>{}, renderSessions=()=>{}, renderNext=()=>{}, renderEvents=()=>{}, renderKpis=()=>{}, renderScope=()=>{}, renderCharts=()=>{}, renderFooter=()=>{};
  const renderHeader=()=>{ $('banner').textContent=''; };
  const renderWaiting=()=>{ $('waiting').textContent=JSON.stringify(data.waiting); };
  const keyOf = text => text.replace(/^\\{"generated_at":"[^"]*",/, '{');
  ${code}
  const response = next => ({ok:true,text:async()=>JSON.stringify(next)});

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
  const timeout=Array.from(timers.values()).find(entry=>entry.delay===REQUEST_TIMEOUT_MS);
  assert.ok(timeout); timeout.fn(); await stalled;
  assert.equal(lost,true); assert.equal($('live').className,'live lost');
  assert.match($('task-body').textContent,/page.task_unavailable/);
  assert.match($('waiting').textContent,/page.nothing_readable/);
  assert.equal($('progress').hidden,true);

  const good=state('recovered','done'); fetch=async()=>response(good); await refresh();
  assert.equal(lost,false); assert.equal(failed,''); assert.equal($('live').className,'live on');
  assert.equal($('banner').textContent,'');
  lost=true; $('banner').textContent='old error'; fetch=async()=>response(good); await refresh();
  assert.equal($('banner').textContent,'');

  document.hidden=true; let calls=0; fetch=async()=>{calls++;return response(state());}; await refresh();
  assert.equal(calls,0);
  return '7 live-page checks passed';
`);
checks(assert).then(result => console.log(result)).catch(error => { console.error(error); process.exitCode=1; });
