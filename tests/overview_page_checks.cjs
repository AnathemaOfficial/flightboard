// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('  // ---- overview:');
const end = source.indexOf('  function renderPublication()', start);
assert.ok(start >= 0 && end > start, 'the actual page implements the overview and prepared actions');
const nodes = new Map();
const roots = [];
const document = {activeElement:null};
class Element {
  constructor(tag, props={}, children=[]) {
    this.tag=tag; this.props=props || {}; this.children=[]; this.parent=null; this.selected=false;
    this.open=Boolean(this.props.open); this.value=''; this.className=this.props.className || '';
    if (this.props.id) nodes.set(this.props.id,this);
    this.replaceChildren(...children);
    if (tag==='textarea') this.value=this.textContent;
  }
  get textContent() { return this.children.map(x=>x instanceof Element?x.textContent:String(x)).join(''); }
  set textContent(value) { this.replaceChildren(String(value)); }
  replaceChildren(...children) {
    this.children.forEach(x=>{if(x instanceof Element)x.parent=null;});
    this.children=children.flat(Infinity).filter(x=>x!==null && x!==undefined && x!==false);
    this.children.forEach(x=>{if(x instanceof Element)x.parent=this;});
  }
  setAttribute(key,value) { this.props[key]=String(value); }
  getAttribute(key) { return this.props[key] ?? null; }
  hasAttribute(key) { return Object.hasOwn(this.props,key); }
  get tagName() { return this.tag.toUpperCase(); }
  get parentElement() { return this.parent; }
  matches() { return true; }
  focus() { document.activeElement=this; }
  select() { this.selected=true; }
  closest() { for(let p=this.parent;p;p=p.parent)if(p.tag==='details'&&!p.open)return p;return null; }
  querySelector() { return this.children.find(x=>x instanceof Element && x.tag==='summary') || null; }
}
const $ = id => {if(!nodes.has(id)){const n=new Element('div',{id});nodes.set(id,n);roots.push(n);}return nodes.get(id);};
const h = (tag,props,...children) => new Element(tag,props,children);
const put = (node,...children) => node.replaceChildren(...children);
const t = (key,args={}) => key+(Object.keys(args).length?' '+JSON.stringify(args):'');
const visit = (root,all=[]) => {all.push(root);root.children.forEach(n=>{if(n instanceof Element)visit(n,all);});return all;};
const all = () => roots.flatMap(n=>visit(n));
document.querySelectorAll = selector => all().filter(n=>selector==='details[data-key]'
  ? n.tag==='details'&&n.props['data-key'] : Boolean(n.props['data-focus']) || n.tag==='summary'&&n.parent?.props['data-key']);
const data = {main:{state:'ok'},generated_at:'2026-11-21T15:00:00-05:00',overview:null};
const context={$,h,put,t,data,document,lost:false,failed:'',label:(group,key)=>key,day:x=>x,
  navigator:{clipboard:{writeText:async text=>{context.writes.push(text);}}},writes:[]};
vm.runInNewContext(source.slice(start,end)+'\nthis.renderOverview=renderOverview;this.preparedPrompt=preparedPrompt;this.copyPreparedAction=copyPreparedAction;',context);
context.hovered=null;context.tipOwner=null;context.quietFocus=false;context.hideTip=()=>{};
const focusStart=source.indexOf('  const focusKey = '), focusEnd=source.indexOf('  const renderCharts = ',focusStart);
vm.runInNewContext(source.slice(focusStart,focusEnd)+'\nthis.redraw=redraw;',context);
const draw=()=>context.renderOverview();
const action=()=>({id:'publish-a',kind:'review_publication',repository:'Scout',ledger:'tasks.json',
  observed_at:'',main_head:'a'.repeat(40),target:'stack',branch:'codex/stack',head:'b'.repeat(40),
  worktree:'worktree-a',tasks:['R2-03'],tasks_more:2,limits:['github_unverified'],more:0});
const overview=()=>({schema_version:1,banner:{state:'attention',code:'local_work'},
  progress:{available:true,main:{total:21,done:12,review:1,in_progress:2},
    live:{total:24,done:18,review:2,in_progress:3},local_only_tasks:3,uncommitted_tasks:2,conflicts:0},
  evidence:{state:'unsupported',scope:'main',verification:'not_evaluated',referenced_tasks:null,
    reference_count:null,references:[],references_more:0,partial:false},actions:[action()]});
async function checks() {
  draw();assert.equal($('overview').hidden,true);
  data.overview=overview();draw();
  assert.equal($('overview').hidden,false);
  assert.match($('overview-banner').textContent,/overview_banner_local_work/);
  assert.match($('overview-progress').textContent,/overview_main/);
  assert.match($('overview-progress').textContent,/overview_live/);
  assert.match($('overview-progress').textContent,/"done":12,"total":21/);
  assert.match($('overview-progress').textContent,/"done":18,"total":24/);
  assert.match($('overview-evidence').textContent,/overview_evidence_unsupported/);
  assert.match($('overview-evidence').textContent,/overview_evidence_note/);
  const prompt=$('prepared-prompt-publish-a');
  assert.equal(prompt.props.readonly,true);
  assert.match(prompt.value,/codex\/stack/);assert.match(prompt.value,/bbbbbbbb/);
  assert.match(prompt.value,/R2-03/);assert.match(prompt.value,/2026-11-21/);
  assert.match(prompt.value,/overview_prompt_tasks_more/);
  assert.equal(context.writes.length,0,'rendering must never write the clipboard');
  const copy=$('prepared-copy-publish-a');
  await copy.props.onclick({isTrusted:false,currentTarget:copy});
  assert.equal(context.writes.length,0,'synthetic clicks cannot copy');
  data.generated_at='2026-11-21T15:00:10-05:00';
  await copy.props.onclick({isTrusted:true,currentTarget:copy});
  assert.equal(context.writes.length,1);assert.match(context.writes[0],/15:00:10/);
  assert.match($('prepared-status-publish-a').textContent,/overview_copied/);
  context.navigator.clipboard.writeText=async()=>{throw new Error('denied');};
  await copy.props.onclick({isTrusted:true,currentTarget:copy});
  assert.equal(document.activeElement,prompt);assert.equal(prompt.selected,true);
  assert.match($('prepared-status-publish-a').textContent,/overview_copy_manual/);
  context.navigator.clipboard=undefined;prompt.selected=false;
  await copy.props.onclick({isTrusted:true,currentTarget:copy});assert.equal(prompt.selected,true);

  const hostile='</textarea><img src=x onerror=alert(1)>';
  data.overview.actions[0].branch=hostile;draw();
  assert.match($('prepared-prompt-publish-a').value,/<img/);
  assert.equal(all().some(n=>n.tag==='img'||n.tag==='script'),false,'source text never becomes markup');
  data.overview.evidence={state:'references_only',verification:'not_evaluated',scope:'main',referenced_tasks:1,
    reference_count:1,references:[{task:'R2-03',status:'done',kind:'tests',at:'2026-11-21',ref:hostile}],references_more:2,partial:true};
  draw();assert.match($('overview-evidence').textContent,/overview_evidence_references_only/);
  assert.match($('overview-evidence').textContent,/overview_evidence_more/);
  assert.match($('overview-evidence').textContent,/overview_evidence_partial/);
  assert.equal(all().some(n=>n.tag==='img'||n.tag==='a'),false,'proof references stay plain text');
  data.overview.evidence.reference_count=null;data.overview.evidence.referenced_tasks=null;draw();
  assert.match($('overview-evidence').textContent,/overview_evidence_unquantified/);
  assert.doesNotMatch($('overview-evidence').textContent,/overview_evidence_references_only/,'unknown totals cannot become zero references');
  const detail=all().find(n=>n.props['data-key']==='prepared-action:publish-a');
  assert.ok(detail);assert.equal($('prepared-copy-publish-a').props['data-focus'],'prepared-copy:publish-a');
  assert.equal($('prepared-prompt-publish-a').props['data-focus'],'prepared-prompt:publish-a');
  detail.open=true;$('prepared-prompt-publish-a').focus();
  const oldField=$('prepared-prompt-publish-a');context.redraw(context.renderOverview);
  assert.notEqual($('prepared-prompt-publish-a'),oldField);
  assert.equal(all().find(n=>n.props['data-key']==='prepared-action:publish-a').open,true,'real redraw restores the open proposal');
  assert.equal(document.activeElement,$('prepared-prompt-publish-a'),'real redraw restores focus to the new prompt');
  context.lost=true;draw();assert.equal($('overview').hidden,true);
  assert.equal($('prepared-actions').textContent,'','lost transport removes prompts and proof verdicts');
  const before=context.writes.length;
  await copy.props.onclick({isTrusted:true,currentTarget:copy});assert.equal(context.writes.length,before);
  context.lost=false;data.main.state='loading';draw();assert.equal($('overview').hidden,true);
  data.main.state='unreadable';draw();assert.equal($('overview').hidden,true);
  data.main.state='ok';data.overview=overview();draw();assert.equal($('overview').hidden,false);
  data.overview.actions=[];draw();assert.match($('prepared-actions').textContent,/overview_no_action/);
  console.log('8 overview-page checks passed');
}
checks().catch(error=>{console.error(error);process.exitCode=1;});
