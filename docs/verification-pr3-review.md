<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# PR 3 review follow-up

Date: 2026-11-18. Initial reviewed head: `5b7374a3ae0b32e70ce08f9e8ed4e0d086389fd6`.
This receipt distinguishes the initial local validation from the later GitHub CI and bot findings.

## Initial external evidence

The initial Windows/Python 3.14, REUSE and strict-manifest jobs passed. The four Linux/macOS test jobs failed
the same assertion that prohibited every `check-ignore` call for a deeply refused ignore file. The new safe
candidate-root query is legitimate; the descendant query must remain refused. Windows/Python 3.12 separately
exposed a fixture cleanup race: a child wrote its receipt before exiting and releasing its temporary CWD.

Codex identified unqueryable candidate names being treated as trusted nonignored file evidence. CodeRabbit's
completed review identified further bounded-reading, ordering, clock and regression-test issues. A completed
CodeRabbit check or a `COMMENTED` review is not an approval.

## Correction areas

- Preserve conservative counts for names that `check-ignore` cannot evaluate, but exclude those untracked
  names from trusted dates and mark their exclusion state partial. Keep tracked names and independently
  evaluated sibling evidence usable.
- Apply entry/deadline bounds while enumerating directory entries. Keep safely observed prefixes after a
  count limit, without dropping an incompletely inspected folder as wholly ignored. Keep independent limit
  and exclusion-failure reasons together.
- Memoize failed fallback observations within one reading and failed parallel Git prefetches within one
  snapshot. Retry after the next snapshot, without retaining filesystem observations across readings.
- Preserve subsecond ordering in observed ledger/file timestamps. Permit observations made during the
  reading, while continuing to refuse dates beyond its completion bound.
- Preserve priority for stash/left-behind alerts, treat healthy refs without a worktree as having no local
  tracking observation, and display the payload's successful-reading time rather than its receipt time.
- Clear initial loading indicators on request failure. Make cache/deadline tests deterministic, verify HEAD
  response status/headers, release blocked readers on failure, and directly observe the parallel-read path
  and first-request timeout origin.
- Verify actual ignore-query input paths in the portable and real FIFO regressions. Wait for the owned
  fixture child to exit before Windows temporary-directory cleanup.

## Verification status

All correction areas above have focused behavioral coverage. The complete final local Windows/Python 3.14
suite ran **619 tests in 286.337 seconds: OK, with 2 skipped** (617 passed). The final integrated run also covers
the ordinary-reading fixtures, actual Node page harness and all previous performance/guard regressions.

An earlier integrated run exposed one more test fixture tied to an exact count of monotonic-clock calls and
the old private collector callback signature. Its replacement advances a controlled clock through success at
129 and expiry at 130, verifies the actual shared deadline and literal error reasons, and checks cleanup.
All 23 mode tests passed separately before the final full run. This changes no production budget rule.

Independent Python, JavaScript, security and general reviews approved the final code and tests. A cross-layer
N/A display issue caught by the general review has actual extracted-page controls for healthy branch/remote
cards and retained warnings for refused local worktrees and broken refs. `git diff --check` passed.

A read-only collector check against the representative three-session checkout still reports complete file
observations and unchanged work counters. Remote CI and bot coverage remain separate checks on the pushed
head, recorded on PR 3; this receipt does not claim those later results or authorize a merge.
