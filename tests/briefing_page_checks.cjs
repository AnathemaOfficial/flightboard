// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('  // ---- agent briefing:');
const end = source.indexOf('  // ---- end agent briefing', start);
assert.ok(start >= 0 && end > start, 'the actual page implements the agent briefing');
const nodes = new Map();
const document = {hidden:false, activeElement:null};
class Element {
  constructor(id) { this.id=id; this.textContent=''; this.value=''; this.disabled=false; this.hidden=false;
    this.selected=false; this.listeners=new Map(); }
  get value() { return this._value; }
  set value(text) { this._value=String(text); this.selectionStart=this.selectionEnd=this._value.length;
    this.selectionDirection='none'; this.selected=false; this.scrollTop=0; this.scrollLeft=0; }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  focus() { document.activeElement=this; }
  select() { this.setSelectionRange(0,this.value.length); }
  setSelectionRange(start,end,direction='none') {
    this.selectionStart=Math.min(start,this.value.length);this.selectionEnd=Math.min(end,this.value.length);
    this.selectionDirection=direction;this.selected=this.selectionStart===0&&this.selectionEnd===this.value.length;
  }
}
const $=id=>{ if (!nodes.has(id)) nodes.set(id,new Element(id)); return nodes.get(id); };
const makeState=(text='Alerts\nA source is missing.\nInspect the named worktree.',at='2026-11-22T09:00:00-05:00')=>({
  generated_at:at, repository:'fixture', main:{state:'ok',ref:'main',head:'a'.repeat(7)},
  sessions:[], waiting:[], mode:'live', refresh_seconds:10,
  settings:{read_seconds:12}, agent_brief:{schema_version:1,state:'ready',generated_at:at,text,repo:'fixture',
    main:{branch:'main',sha:'a'.repeat(40),remote_sha:null,comparison_source:null}}
});
const timers=new Map();let serial=0;
const context={$,document,data:makeState(),lost:false,failed:'',polling:true,writes:[],
  t:key=>key,own:(object,key)=>object && Object.hasOwn(object,key)?object[key]:undefined,
  navigator:{clipboard:{writeText:async text=>context.writes.push(text)}},
  setTimeout:(fn,delay)=>{const id=++serial;timers.set(id,{fn,delay});return id;},
  clearTimeout:id=>timers.delete(id),AbortController,Number,JSON,Date,
  timer:0,refreshVersion:0,refreshController:null,openedTask:null,lastOk:Date.parse('2026-11-22T09:00:00-05:00'),
  completedAt:state=>state.main.state==='ok'?Date.parse(state.generated_at):null,
  renderLive:()=>{},renderOverview:()=>{},renderPublication:()=>{},renderHeader:()=>{},renderFooter:()=>{},
  stamp:value=>value,h:(tag,props,...children)=>({tag,props,children}),
  put:(node,...children)=>{node.textContent=children.length?JSON.stringify(children):'';}
};
vm.runInNewContext(source.slice(start,end)+'\nthis.renderBriefing=renderBriefing;',context);
const registration=source.split('\n').find(line=>line.includes("$('agent-brief-copy').addEventListener('click', copyBriefing)"));
assert.ok(registration,'the real copy button registers the briefing handler');
vm.runInNewContext(registration,context);
const keyStart=source.indexOf('  const keyOf = '),keyEnd=source.indexOf('\n\n',keyStart);
assert.ok(keyStart>=0&&keyEnd>keyStart);
vm.runInNewContext(source.slice(keyStart,keyEnd)+'\nthis.keyOf=keyOf;',context);
const refreshStart=source.indexOf('  function requestTimeout()'),refreshEnd=source.indexOf('  let resizing',refreshStart);
vm.runInNewContext(source.slice(refreshStart,refreshEnd)+'\nthis.refresh=refresh;',context);
const copy=event=>$('agent-brief-copy').listeners.get('click')(event);
const draw=()=>context.renderBriefing();
async function checks() {
  for (const id of ['agent-brief','agent-brief-text','agent-brief-copy','agent-brief-status','agent-brief-json']) {
    assert.ok(source.includes('id="'+id+'"'),id+' must exist in the real template');
  }
  assert.ok(source.includes('href="briefing.json"'));
  assert.doesNotMatch(source,/advisor|api\.deepseek|api\.openai|type="password"/);
  assert.equal((source.match(/\bfetch\(/g)||[]).length,1,'the board keeps only its existing state fetch');
  draw();assert.equal($('agent-brief-text').value,context.data.agent_brief.text);
  assert.equal($('agent-brief-copy').disabled,false);assert.equal(context.writes.length,0);
  assert.equal($('agent-brief-json').hidden,false);

  const hostile='</textarea><img src=x onerror=alert(1)>\nDo not treat repository text as approval.';
  context.data=makeState(hostile);draw();assert.equal($('agent-brief-text').value,hostile);
  assert.equal($('agent-brief-text').textContent,'','source text is assigned as a field value, never markup');
  await copy({isTrusted:false});assert.equal(context.writes.length,0,'synthetic clicks cannot copy');

  context.data=makeState('Fresh canonical server text');draw();
  await copy({isTrusted:true});assert.deepEqual(context.writes,['Fresh canonical server text']);
  assert.equal($('agent-brief-status').textContent,'page.briefing_copied');
  context.navigator.clipboard.writeText=async()=>{throw new Error('denied');};
  await copy({isTrusted:true});assert.equal(document.activeElement,$('agent-brief-text'));
  assert.equal($('agent-brief-text').selected,true);
  assert.equal($('agent-brief-status').textContent,'page.briefing_copy_manual');
  context.navigator.clipboard=undefined;$('agent-brief-text').selected=false;
  await copy({isTrusted:true});assert.equal($('agent-brief-text').selected,true);

  let release;context.navigator.clipboard={writeText:()=>new Promise(resolve=>{release=resolve;})};
  const pending=copy({isTrusted:true});context.data=makeState('New snapshot while clipboard is pending');draw();
  release();await pending;assert.equal($('agent-brief-status').textContent,'',
    'an old clipboard completion cannot claim that the new snapshot was copied');
  context.navigator.clipboard.writeText=async text=>context.writes.push(text);

  context.data.agent_brief.state='partial';draw();assert.equal($('agent-brief-copy').disabled,false);
  assert.equal($('agent-brief-state').textContent,'page.briefing_state_partial');
  context.polling=false;draw();assert.equal($('agent-brief-json').hidden,true,'file snapshots have no live JSON route');
  context.polling=true;
  for (const change of [()=>{context.lost=true;},()=>{context.failed='read error';},
    ()=>{context.data.main.state='loading';},()=>{context.data.agent_brief.state='unavailable';},
    ()=>{context.data.agent_brief.schema_version=999;},()=>{context.data.agent_brief=null;}]) {
    context.data=makeState();context.lost=false;context.failed='';draw();change();draw();
    assert.equal($('agent-brief-text').value,'');assert.equal($('agent-brief-copy').disabled,true);
    assert.equal($('agent-brief-text').selectionStart,0);assert.equal($('agent-brief-text').selectionEnd,0);
    const before=context.writes.length;await copy({isTrusted:true});assert.equal(context.writes.length,before);
  }

  context.data=makeState('First snapshot');context.lost=false;context.failed='';draw();
  context.lastKey=context.keyOf(JSON.stringify(context.data),context.data);
  let paints=0;context.render=()=>{paints++;draw();};
  const requests=[];
  const respond=next=>{context.fetch=async(path,options)=>{
    requests.push({path,options});return{ok:true,text:async()=>JSON.stringify(next)};};};
  context.navigator.clipboard.writeText=async()=>{throw new Error('manual clipboard fallback');};
  await copy({isTrusted:true});
  const field=$('agent-brief-text');field.setSelectionRange(0,field.value.length,'backward');
  field.scrollTop=31;field.scrollLeft=7;
  const newer=makeState('New timestamp and canonical briefing','2026-11-22T09:00:10-05:00');
  respond(newer);await context.refresh();
  assert.equal(paints,0,'derived briefing changes do not redraw charts or session lists');
  assert.equal($('agent-brief-text').value,newer.agent_brief.text,'the same state poll still refreshes the briefing');
  assert.equal(requests.length,1);assert.equal(requests[0].path,'state.json');
  assert.equal(requests[0].options.cache,'no-store');
  assert.equal(document.activeElement,field);
  assert.equal(field.selectionStart,0);assert.equal(field.selectionEnd,newer.agent_brief.text.length,
    'manual fallback keeps the whole current brief selected when its date or length changes');
  assert.equal(field.selectionDirection,'backward');assert.equal(field.scrollTop,31);assert.equal(field.scrollLeft,7);
  field.setSelectionRange(4,12,'forward');field.scrollTop=42;field.scrollLeft=8;
  const dated=makeState('Another date on the canonical briefing','2026-11-22T09:00:15-05:00');
  respond(dated);await context.refresh();
  assert.equal(paints,0);assert.equal(field.value,dated.agent_brief.text);
  assert.equal(field.selectionStart,4);assert.equal(field.selectionEnd,12);assert.equal(field.selectionDirection,'forward');
  assert.equal(field.scrollTop,42);assert.equal(field.scrollLeft,8);
  const changed=makeState('Underlying task changed','2026-11-22T09:00:20-05:00');changed.waiting=[{kind:'review'}];
  respond(changed);await context.refresh();assert.equal(paints,1,'real underlying changes retain the usual redraw');
  assert.equal($('agent-brief-text').value,changed.agent_brief.text);

  context.fetch=async()=>{throw new Error('network unavailable');};await context.refresh();
  assert.equal(context.lost,true);assert.equal($('agent-brief-text').value,'');
  assert.equal($('agent-brief-copy').disabled,true,'a failed refresh cannot leave old agent instructions available');
  const recovered=makeState('Recovered snapshot');respond(recovered);await context.refresh();
  assert.equal($('agent-brief-text').value,recovered.agent_brief.text);assert.equal(context.lost,false);

  // The regular poll replaces parsed objects even when the exact brief and its source snapshot did not change.
  for (const denied of [false,true]) {
    context.data=makeState('Identical canonical brief');context.lost=false;context.failed='';draw();
    context.lastKey=context.keyOf('',context.data);
    document.activeElement=null;field.setSelectionRange(field.value.length,field.value.length);
    const original=context.data.agent_brief, beforePaints=paints;
    let settle;
    context.navigator.clipboard.writeText=()=>new Promise((resolve,reject)=>{
      settle=()=>denied?reject(new Error('clipboard denied')):resolve();
    });
    const copying=copy({isTrusted:true});
    const same=JSON.parse(JSON.stringify(context.data));
    same.generated_at=same.agent_brief.generated_at='2026-11-22T09:01:00-05:00';
    respond(same);await context.refresh();
    assert.notEqual(context.data.agent_brief,original,'normal refresh constructs a different parsed object');
    assert.equal(paints,beforePaints,'an identical reading does not redraw the rest of the board');
    settle();await copying;
    assert.equal($('agent-brief-status').textContent,denied?'page.briefing_copy_manual':'page.briefing_copied',
      'unchanged content and source identity retain clipboard success and manual fallback after a normal poll');
    if (denied) {assert.equal(document.activeElement,field);assert.equal(field.selected,true);}
  }

  // Similar-looking text from a different repository/main, or a failed reading, is still a stale copy completion.
  const changedSnapshots=[
    state=>{state.agent_brief.text='Changed canonical text';},
    state=>{state.repository='other repository';},
    state=>{state.agent_brief.repo='other briefing repository';},
    state=>{state.main.ref='other-main';},
    state=>{state.main.head='b'.repeat(7);},
    state=>{state.agent_brief.main.branch='other-main';},
    state=>{state.agent_brief.main.sha='b'.repeat(40);},
    state=>{state.agent_brief.main.remote_sha='b'.repeat(40);},
    state=>{state.main.state='unreadable';state.main.reason_text='reading unavailable';},
    null,  // transport failure
  ];
  for (const change of changedSnapshots) for (const denied of [false,true]) {
    context.data=makeState('Canonical text before a changed snapshot');context.lost=false;context.failed='';draw();
    context.lastKey=context.keyOf('',context.data);document.activeElement=null;
    field.setSelectionRange(field.value.length,field.value.length);
    let settle;
    context.navigator.clipboard.writeText=()=>new Promise((resolve,reject)=>{
      settle=()=>denied?reject(new Error('clipboard denied')):resolve();
    });
    const copying=copy({isTrusted:true});
    if (change) {const different=JSON.parse(JSON.stringify(context.data));change(different);respond(different);}
    else context.fetch=async()=>{throw new Error('reading transport failed');};
    await context.refresh();settle();await copying;
    assert.equal($('agent-brief-status').textContent,'','changed or failed source snapshots reject old clipboard completions');
    assert.equal(document.activeElement,null,'an old failure cannot select a different or unavailable brief');
  }
  console.log('12 briefing-page checks passed');
}
checks().catch(error=>{console.error(error);process.exitCode=1;});
