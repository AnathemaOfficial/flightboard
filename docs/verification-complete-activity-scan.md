<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Complete activity scan verification

Date: 2026-11-18. Scope: [design](superpowers/specs/2026-11-18-complete-activity-scan-design.md).

## Diagnosis

Scout's working checkout contains 424 tracked files, 18 modified files and 335 nonignored untracked files.
The existing display correctly collapses the latter into 45 candidates. The ordinary documentary evidence
folders exceed the old three-level/200-entry child limits; their already obtained dates also exceed the old
200-name activity selector. These are three actual truncations, not a refused repository or missing authority.

## Candidate checks

The new regressions reproduced the old failures before implementation: already observed leaves beyond 200,
a 300-file ordinary folder, a deeper source tree and premature traversal of an ignored root. A shared budget
regression also protects bounded work across multiple candidate folders.

An initial read-only check of the corrected collector against actual Scout files reports all three sessions
complete, with no partial reasons and the same modified/untracked counters. No Scout file was changed.
Four snapshots using the same settings measured 0.8061 seconds cold and 0.4961 seconds warm median before;
the initial candidate measured 0.8122 seconds cold and 0.5120 seconds warm median. Each warm median has three
samples; this is a local comparison, not a general performance guarantee.

## Final validation

- Full project suite: `python -I -B -m unittest discover -s tests -t .` through RTK, **598 tests in 272.569 seconds,
  OK with 2 skipped** (596 passed). This includes the 12 new scan-budget regressions.
- Operational helper: 16 pure temporary/fault tests passed, independently rerun by the Python reviewer.
- Python, security and general reviews: APPROVE on the final source/helper hashes; no actionable finding.
- `git diff --check`: passed. Existing parallel/path-plan tests and all prior tracking regressions are included
  in the full suite. No JavaScript or page-template change is part of this correction.

## Installed result

The four installed engine copies now match payload digest
`e15d0c83d1bf727d13f19b0c53c1245ae8fc49f61abe532130a17e191d870cef`.
Only Scout and its supervisor restarted. All eight other board process identities, including SYFOS, were
preserved. Startup remains enabled with the same nine boards, exact configuration bytes and two authorized
Scout roots. No Scout project file or task state was changed by this correction.

The installed API reports all three Scout sessions with readable files, valid ledgers, complete ordinary-file
observations, no partial reasons and `tracking.state=none`. The development worktree still has 18 modified and
45 collapsed untracked candidates. The existing browser page refreshed automatically: no tracking notice,
no unevaluated-association text and all maintenance lot IDs remain visible.

Four installed-engine snapshots measured **0.8611 seconds cold / 0.5237 seconds warm median**; the warm samples
were 0.5292, 0.5158 and 0.5237 seconds. The comparison preserves bounded work and the existing optimizations;
it does not promise identical timings on every run. Future genuine scan-budget/security limits remain explicit.
Complete dating does not establish per-file lot coverage or acceptance.

The external artifact folder `flightboard-complete-scan-20261118` contains pre-change hashes/patch, timing
records, test results and the installation receipt/backup. No commit, push or merge was performed.
