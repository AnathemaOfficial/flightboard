<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Complete ordinary-tree observations within shared bounds

The owner requested correcting Scout's remaining partial scan while preserving performance.

## Root cause and scope

Scout has 18 modified tracked files and 335 nonignored untracked files, displayed as 45 collapsed candidates.
The three-level/200-entry per-folder traversal cannot finish ordinary evidence folders; the activity selector
then discards dates past 200 even when their guarded metadata has already been obtained. Raising every limit
would retain unnecessary filesystem work and would still let ignored output consume the envelope.

## Design

- Keep guarded manual discovery, candidate counters, authorized roots and unchanged-tracked metadata exclusion.
  Do not introduce Git untracked traversal or filesystem caches between snapshots.
- Prune confirmed ignored candidate roots in one guarded batch before listing their descendants. Keep the
  existing batch for descendant exclusions. No Git subprocess per directory. A failed exclusion check remains
  explicit and cannot supply trusted untracked-file observations.
- Give all child traversals of one worktree a shared 2000-entry budget and eight-level depth bound. Count each
  inspected directory/file/special entry before obtaining its metadata, and check the snapshot deadline before
  each folder and entry. Once exhausted, do not list remaining candidate folders. Metadata retained by this
  phase is bounded by that same envelope; top-level candidates/changed-file observations remain separately bounded.
- Reuse every selected ordinary-file observation obtained within those bounds. Keep 200 as the allowance for
  additional fallback metadata lookups, rather than truncating already available leaf dates. Reuse must not
  trigger a second stat for an already observed file.
- Keep honest partial results for genuine budget/depth exhaustion, failed exclusions, unreadable files,
  deletions, links/junctions/special entries and nested repositories. Directory dates remain legacy activity,
  never positive ordinary-file evidence. No task status, acceptance rule or progress calculation changes.
- Preserve parallel readers, immutable text/path-plan caches, and the existing whole-reading budget.

## Validation and local delivery

Write RED/GREEN regressions for more than 200 observed leaves, a normal deeper source tree, ignored-root pruning,
shared budget exhaustion, deadline propagation, fallback lookup bounds, fresh leaf observations and existing
unsafe/nested-repository cases. Verify counter and parallel/sequential equivalence and run the full suite.
Independently review Python, security and final changes. Compare actual Scout cold/warm snapshot timings before
and after, with all current working files preserved.

Back up installed payloads and configuration. Update the four existing engine copies and restart only Scout
and its supervisor; preserve every other board process, configuration and exact authorized root. Verify API
and browser state on the real board. No Scout project edit, provider call, commit, push or merge belongs here.
