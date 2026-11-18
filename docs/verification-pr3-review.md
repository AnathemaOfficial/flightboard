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

## Live clock and visible-detail follow-up

The next external pass on `fcd32d27ae60a12634a91f331a1f0091fd9f04b0` classified risk as low and raised smaller
clock, display-budget and test-boundary issues. The live server now supplies a trusted completion wall clock;
fixed-time snapshots retain their deterministic time model and monotonic deadlines remain independent of clock
corrections. The clock hook must not disable normal parallel readers or permit arbitrary instance reader overrides.

Review actions precede informational tracking reminders. Visible next-task details are reserved before reminder
IDs, and hidden waiting rows do not preempt details for visible cards. A known enumeration limit is retained even
when an entry disappears before classification. Tests observe deadlines outside callbacks that intentionally catch
errors, expire worker deadlines only after the initial batch is submitted, identify the actual forked failure
runners, distinguish initial abort/poll timers and allow fixture setup time before the child watchdog expires.

The additional request to infer changes that happen between separate file and ledger observations is outside
the temporal-hint contract: `none` means no temporal gap was observed, never atomic coverage. An active worktree
is not an atomic snapshot. A later ledger save can remove the signal without proving every change was registered,
as the README and tracking design already state. Another traversal would add work and still have its own race
window; this correction adds no journal, second full walk or automatic acceptance inference.

The final follow-up suite ran **628 tests in 293.158 seconds: OK, with 2 skipped** (626 passed). Focused clock,
budget, priority/detail, parallel, mode, startup and actual Node-page checks passed. Independent Python,
JavaScript, security and general reviews approved the final source and tests.

The review caught a temporary interaction between the trusted clock callback and the conservative instance-spy
guard. Only the explicit `_completion_clock` field is exempted; custom reader overrides still select sequential
execution. A RED/GREEN regression on eight real worktrees verifies actual forked readers, equivalent complete
results and the custom-operation refusal control.

Four read-only checks with the live clock configured report parallel reading enabled, all three representative
sessions complete and unchanged work counters. Cold latency was 0.8713 seconds; the three warm samples gave
a **0.4967-second median**. This is a local measurement, not a guarantee for other repositories or machines.

## Bounded failure recovery and fixture ownership

A further low-risk review of `be12036d64af066d4327aef1894801abbb80584d` identified additional edge cases.
Remote-ancestry failures now use the same per-reading discipline as pair/range failures: the parent publishes
direction-specific failures, preserves a successful forward `False` result when the reverse query fails, and
retries after the next snapshot. A directly verified nonignored file retains its observation when only the
descendant exclusion batch fails. Unsupported names and unverified descendants remain untrusted.

A budgeted candidate-folder enumeration that observes a disappearance or folder-to-file replacement returns
an incomplete result, never an empty-folder proof. The next reading recovers normally. Interactive task/event
details are reserved before completed history and informational reminders under the existing 500-detail cap;
tests exercise 520 distinct reminder IDs and a current visible card.

The Windows startup fixture transfers the actual child process handle to the test process before status writes,
independently of stdout. Cleanup terminates and waits only its owned processes, stops the child before draining
captured caller pipes, and retains the primary exception if cleanup reports another error. Failure tests cover
status output, caller timeout, malformed output, gate creation, child waiting, handle acquisition, inherited
captured pipes and primary-error preservation. No production startup implementation or live service is changed
by this fixture work; no child is terminated by an unverified or reusable PID.

The final full local Windows/Python 3.14 suite ran **638 tests in 338.514 seconds: OK, with 2 skipped**
(636 passed). Independent Python, security and general follow-up reviews approved the final code and fixture;
the previously approved JavaScript is unchanged. The latest live-clock check kept parallel readers enabled,
all three sessions complete and counters unchanged, with a **0.5123-second warm median** across three samples.
The pushed-head CI and provider reviews are recorded separately on the PR.

## Session isolation and detail-priority follow-up

The `cdffbb64761a3bc5ab37aacbe37f212cdbeb01eb` revision passed all eight CI jobs and its Codex review
reported no findings. CodeRabbit subsequently identified a session-isolation regression and two remaining
detail-priority cases. A failed session remote-ancestry comparison must remain unreadable without failing
healthy sessions or claiming a pushed, behind or diverged relationship. The repository-wide deadline must
still propagate. Quiet-session historical IDs and head-ledger completed tasks must not displace current
interactive details under the existing cap. These are production behavior corrections, separate from
test-harness reliability suggestions.

At `bef7025`, the Windows test fixture had an explicitly deferred limitation (CodeRabbit `r4616388591`): a caller stalled
between duplicating a child handle and publishing its ownership record can leave the child alive until its
30-second watchdog expires, and the duplicated handle can remain open until the test process exits. Normal
handoff and exceptions that run the rescue path are covered; a stalled handoff is not. A test-owned Windows
job established before child launch would close that gap, but requires a separate fixture-lifecycle change.
This is a test-only failure window, not a production startup fix or a claim of unconditional fixture ownership.

The session-isolation regression failed before correction and now preserves main and healthy worktrees for
both worktree and unheld-branch failures. Reciprocal ancestry jobs share one worker without losing directional
failure evidence, and the shared-deadline control still fails the whole reading. Two detail-cap regressions
cover quiet-session reminders and completed tasks declared only in a session ledger. Fixture controls verify
atomic receipt publication, explicit wait-timeout injection and child-held pipes after caller exit.

The final full local Windows/Python 3.14 suite ran **644 tests in 305.763 seconds: OK, with 2 skipped**
(642 passed). Independent Python, general and security reviews approved these source/test hashes; unchanged
JavaScript retains its earlier verification. `git diff --check` passed, and the original performance worktree's
dirty-patch SHA-256 remains `9f2f73c70e82cf42f06ef2da888f8c6c971eee561b9484e54203df8eaba8139c`.
Later pushed-head CI and bot results are separate PR evidence; the test-only item was still open at that revision.

## Remaining CodeRabbit corrections requested after `bef7025`

The follow-up addresses review `5960056746` and the earlier Windows fixture ownership comment. Unknown main
distances now produce an explicit indeterminate stage in English and French, with no merged advice. Confirmed
merged, dirty, conflict and operation evidence retains its established priority. Visible quiet-session reminders
reserve details for ongoing tasks, using live status and then their declaring ledger; completed history remains
later under the same 500-detail cap.

Requested reciprocal ancestry directions stay in the forked worker pool, including a successful first direction
and direction-specific failures. Planning and workers reuse both success and failure memos across the worktree
and branch phases: an unknown opposite direction is still scheduled, while a failed direction is not retried
within the reading. Single-direction early stopping, parent-only result publication and shared deadlines remain.
Regressions cover both prefetch phases, actual child runners, no serial fallback and both direct and forked
deadline propagation. No additional traversal, per-folder Git query or filesystem cache is introduced.

The Windows fixture now owns an anonymous, non-inheritable Job with kill-on-close before opening the controlled
caller's bootstrap gate. It publishes only a PID atomically and opens the observation handle in the test process,
requiring membership in that exact Job before trusting it. Cross-process handle duplication is removed, so a stall
before publication leaves no transferred parent handle. Job cleanup covers the launched but unpublished child;
the Job remains owned through the caller-exit and child-survival receipt assertions. Unconfirmed caller waits keep
Popen's native handle available for recovery, and the wait-failure control starts with genuinely open pipes.

The reviewed Windows Python 3.12 and 3.14 executables are direct interpreters, as is the CI's setup-python path.
The containment evidence applies to those paths; assigning a launcher does not retrospectively contain an
interpreter it already started. The fixture makes no universal guarantee for an arbitrary delegating launcher.
No production startup code, installed engine, supervisor or running dashboard is changed by this test work.

Focused verification: 23 parallel-reading tests, 26 tracking tests, 46 overlay tests and 6 catalog tests passed.
The Windows fixture passed 62 tests on Python 3.14 (15.170 seconds) and Python 3.12 (14.519 seconds). A no-op
Job-termination mutation makes the unpublished-child regression fail; real kill-on-close cleanup remains enabled
during that control. Python, general and security reviews and the final full-suite results are recorded below.

Independent Python, general and security reviews approved the final source and fixture hashes. A fresh read-only
live-clock check kept parallel reading enabled, all three Scout sessions complete and their work counters unchanged.
Its cold sample was 0.9193 seconds; the median of three warm samples was 0.5474 seconds during local validation.
This is a local observation, not a cross-machine latency guarantee. The separate original performance worktree's
dirty-patch SHA-256 still matches `9f2f73c70e82cf42f06ef2da888f8c6c971eee561b9484e54203df8eaba8139c`.

The final full local Windows/Python 3.14 suite ran **652 tests in 317.262 seconds: OK, with 2 skipped**
(650 passed). This includes the hygiene checks, unchanged extracted Node-page harness and previous scan/cache
regressions. `git diff --check` passed. Pushed-head CI and provider review outcomes are verified separately on PR 3;
the earlier green run for `bef7025` is not substituted for these checks.
