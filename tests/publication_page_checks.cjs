// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('  function renderPublication()');
assert.ok(start >= 0, 'the actual page implements publication rendering');
const end = source.indexOf('  // ---- what waits', start);
const nodes = new Map();
const $ = id => { if (!nodes.has(id)) nodes.set(id, {hidden:false, children:[],setAttribute(){}}); return nodes.get(id); };
const h = (tag, props, ...children) => ({tag, props, children});
const put = (node, ...children) => { node.children = children.flat(Infinity).filter(x => x !== null && x !== undefined && x !== false); };
const t = (key, args={}) => key + JSON.stringify(args);
const stamp = value => value;
const live = value => value;
let data = {};
const render = new Function('$','h','put','t','stamp','live','data', source.slice(start, end) + '\nrenderPublication();');
const draw = () => render($,h,put,t,stamp,live,data);
const text = id => JSON.stringify($(id).children);
draw();
assert.equal($('publication').hidden, true, 'neutral loading snapshots have no invented publication facts');
data.publication = {
  remote:{state:'fresh',repository:'owner/repo',last_success_at:'2026-11-21T12:00:00-05:00',complete:true},
  main:{state:'equal',ahead:0,behind:0,comparison_source:'github'},
  coverage:{worktrees_discovered:16,working_files_read:3,working_files_unknown:13,reasons:{outside:13}},
  unpublished:{state:'exact',unique_commits:8,candidate_commits:8,comparison_source:'github'},
  alerts:[{code:'worktree_coverage',detail:'13',severity:'warning',first_seen_at:null}],
  queue:[{kind:'commits',branches:['stack-A','stack-B'],worktrees:[],head:'a'.repeat(40),commit_count:5,
    candidate_count:5,state:'unpublished',comparison_source:'github',pull_requests:[{number:3,title:'Review <script>',url:'javascript:alert(1)'}]}]
};
draw();
assert.equal($('publication').hidden,false);
assert.match(text('publication-cards'),/8/);
assert.match(text('publication-cards'),/13/);
assert.match(text('publication-alerts'),/worktree_coverage/);
assert.match(text('publication-queue'),/stack-A.*stack-B/);
assert.match(text('publication-queue'),/https:\/\/github.com\/owner\/repo\/pull\/3/);
assert.doesNotMatch(text('publication-queue'),/javascript:/);
data.publication.remote.state='stale';
data.publication.unpublished={state:'partial',unique_commits:null,candidate_commits:8,comparison_source:'local_tracking_refs'};
data.publication.queue=[{kind:'dirty',branches:[],worktrees:['unread'],head:'',files:null,state:'unknown',pull_requests:[]}];
draw();
assert.match(text('publication-cards'),/publication_remote_stale/);
assert.match(text('publication-cards'),/publication_candidates/);
assert.doesNotMatch(text('publication-queue'),/stack-A/,'refresh replaces old queue');
assert.match(text('publication-queue'),/publication_files_unknown/);
data.publication.queue=[{kind:'review',state:'pr_open',branches:['published'],worktrees:[],head:'a'.repeat(40),
  commit_count:0,branches_more:3,worktrees_more:0,pull_requests:[{number:3,title:'Review'}]}];
data.publication.queue_more=10;
draw();
assert.match(text('publication-queue'),/publication_queue_pr_open/);
assert.match(text('publication-queue'),/publication_queue_more/);
assert.match(text('publication-queue'),/publication_aliases_more/);
assert.doesNotMatch(text('publication-queue'),/publication_commits/,'published PRs have their own review stage');
data.publication.coverage={worktrees_discovered:2,worktree_files_total:1,working_files_read:1,
  working_files_unknown:0,reasons:{link:1},reason_labels:{link:'Link refused'},worktrees:[]};
draw();
assert.match(text('publication-cards'),/\\"read\\":1,\\"total\\":1/);
assert.match(text('publication-cards'),/Link refused/);
assert.doesNotMatch(text('publication-cards'),/publication_reason_link/);
console.log('5 publication-page checks passed');
