// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('  function renderDaily(box) {');
const finish = source.indexOf('  // ---- footer and the whole page', start);
assert.ok(start >= 0 && finish > start, 'execute the daily chart from the actual page template');
const code = source.slice(start, finish);
const keys = ['new_main', 'progress_main', 'review_main', 'done_main',
  'new_live', 'progress_live', 'review_live', 'done_live'];
const names = keys.map(key => 'page.d_' + key);
const colors = ['var(--ready)', 'var(--progress)', 'var(--review)', 'var(--done)'];

function render(days) {
  const hits = [], scales = [];
  const node = (tag, props = {}, ...children) => ({tag, props, children,
    append(...added) { this.children.push(...added); }});
  const box = node('box');
  const linear = (d0, d1, r0, r1) => {
    scales.push({d0, d1});
    return value => r0 + (value - d0) * (r1 - r0) / (d1 - d0);
  };
  const draw = new Function('data', 'h', 's', 'put', 't', 'widthOf', 'niceStep', 'linear', 'svgRoot',
    'shortDate', 'endRounded', 'hoverable', 'day', 'tipRow', 'legend', 'tableView', 'box',
    code + '\nrenderDaily(box);');
  draw({daily: days}, node, node, (target, ...children) => { target.children = children; }, key => key,
    () => 640, maximum => Math.max(1, Math.ceil(maximum / 4)), linear,
    (width, height, title) => node('svg', {width, height, title}), value => value,
    (...coordinates) => JSON.stringify(coordinates),
    (shape, rows, aria, key) => { hits.push({rows, aria, key}); return shape; }, value => value,
    (color, name, value) => ({color, name, value}), entries => ({tag: 'legend', entries}),
    (key, headers, rows) => ({tag: 'table', key, headers, rows}), box);
  const svg = box.children.find(child => child.tag === 'svg');
  return {box, svg, hits, scales,
    paints: svg ? svg.children.filter(child => colors.includes(child.props.fill)) : [],
    legend: box.children.find(child => child.tag === 'legend'),
    table: box.children.find(child => child.tag === 'table')};
}

// Creations and starts remain visible even when no task finished or entered review.
const additions = render([{day: '2026-11-19', new_main: 2, new_live: 1}]);
assert.equal(additions.paints.length, 2, 'new-task-only data must paint both main and session additions');
assert.deepEqual(additions.paints.map(shape => [shape.props.fill, shape.props.opacity]),
  [['var(--ready)', 1], ['var(--ready)', .45]]);
const starts = render([{day: '2026-11-19', progress_main: 1, progress_live: 3}]);
assert.deepEqual(starts.paints.map(shape => [shape.props.fill, shape.props.opacity]),
  [['var(--progress)', 1], ['var(--progress)', .45]]);

// Every representation uses the same eight categories and stack scale, including overlapping movements.
const values = Object.fromEntries(keys.map((key, i) => [key, i + 1]));
const all = render([{day: '2026-11-19', ...values}]);
assert.equal(all.paints.length, 8);
assert.equal(all.scales[0].d1, 36, 'the axis includes all eight series, not only completion movements');
assert.deepEqual(all.legend.entries.map(entry => entry[1]), names);
assert.deepEqual(all.legend.entries.map(entry => entry[2]), ['', '', '', '', 'light', 'light', 'light', 'light']);
assert.deepEqual(all.table.headers, ['page.h_day', ...names]);
assert.deepEqual(all.table.rows, [['2026-11-19', 1, 2, 3, 4, 5, 6, 7, 8]]);
assert.equal(all.table.key, 'table:daily', 'keep the existing table state key');
assert.equal(all.hits.length, 1, 'one interactive region per day, not per series');
assert.equal(all.hits[0].key, 'zone:daily|2026-11-19');
const tip = all.hits[0].rows();
assert.deepEqual(tip[1].map(row => [row.name, row.value]), names.map((name, i) => [name, i + 1]));
for (const [i, name] of names.entries()) assert.ok(all.hits[0].aria.includes(name + ' ' + (i + 1)));

// Older snapshots without new fields retain their completion counts and show explicit zero cells.
const legacy = render([{day: '2026-11-18', done_main: 2, review_main: 1, done_live: 3, review_live: 4},
  {day: '2026-11-19', done_main: 1}]);
assert.deepEqual(legacy.table.rows, [
  ['2026-11-19', 0, 0, 0, 1, 0, 0, 0, 0],
  ['2026-11-18', 0, 0, 1, 2, 0, 0, 4, 3]]);
assert.doesNotMatch(JSON.stringify(legacy.box), /NaN/);
assert.deepEqual(legacy.hits[1].rows()[1].map(row => row.value), [0, 0, 0, 1, 0, 0, 0, 0]);

const empty = render([]);
assert.equal(empty.svg, undefined);
assert.deepEqual(empty.box.children[0].children, ['page.no_moves']);
assert.equal(empty.hits.length, 0);

// Rendering remains bounded by the existing fourteen days and does not mutate cached readings.
const days = Object.freeze(Array.from({length: 14}, (_, i) =>
  Object.freeze({day: '2026-11-' + String(i + 6).padStart(2, '0'), ...values})));
const bounded = render(days);
assert.equal(bounded.hits.length, 14);
assert.equal(new Set(bounded.hits.map(hit => hit.key)).size, 14);
assert.equal(bounded.paints.length, 14 * 8);
assert.equal(bounded.table.rows.length, 14);
assert.equal(days[0].day, '2026-11-06');
console.log('6 daily-chart checks passed');
