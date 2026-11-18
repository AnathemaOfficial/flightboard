<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Tracking freshness V1 verification

Date: 2026-11-17. Scope: [approved design](superpowers/specs/2026-11-17-tracking-freshness-design.md)
and [implementation plan](superpowers/plans/2026-11-17-tracking-freshness.md).

## Source identity

Local uncommitted changes on baseline `f874bbca5ec59dcaae3e63fb060e5b9d511e4d43`, preserving the earlier
reviewed local fixes. The complete 25-file runtime payload digest is
`86dce9dc5fbc744bdcfc84403cee2dab145146f14e385016413d6cb7afccb1f5`.
No publication or remote CI execution is asserted.

## Automated validation

- Complete Windows suite: **573 tests in 341.991 seconds, OK, 2 skipped** (571 passed).
- New metadata regressions: 11, with real temporary Git/filesystem observations and metadata-call bounds.
- New classification regressions: 12, including the known old task ID, all internal IDs before presentation caps,
  incomplete dating, ongoing/blocked work, ledger-only edits and task/KPI/event/readiness invariance.
- Existing file/path-plan/parallel-reading regressions passed: 42 / 11 / 12.
- Existing overlay and message-catalog tests passed: 46 / 6.
- Actual page JavaScript checks passed: 13 groups, including dates, failed refresh/recovery and malformed values.
- Generic, Python and JavaScript source reviews approved the integrated implementation.

## Browser and installation evidence

A disposable repository and loopback server exercised the actual browser polling in one page/process:
`none -> check -> info -> none`. Code activity newer than the saved ledger raised a notice even with an old
known task ID; an in-progress task produced information; saving the ledger removed the temporal signal without
inventing a coverage verdict or changing that task. The three dates were rendered visibly. There were no manual
browser fetches or reloads. A 390px viewport had no horizontal overflow. The final run passed 12 orchestration
assertions and 16 browser assertions; loaded source hashes matched the final candidate and all owned temporary
resources were cleaned up.

Review found two issues confined to the disposable test harness: cleanup after a failed thread start, and an
assertion that incorrectly required minute-rounded timestamps to differ. Both were corrected with RED/GREEN
regressions, independently re-reviewed and followed by a successful real browser rerun. These findings did not
change product source.

The four installed runtime copies match the payload digest. The two selected dashboards returned HTTP 200 and
main.state=ok; the startup supervisor is enabled/running. Configuration bytes and the other seven board process
identities remained unchanged. A full pre-install backup and external verification receipts were retained.

## Evidence boundaries

- File activity is an observation, not proof of which lot it belongs to. No diagnostic changes task states,
  progress history, merge advice or owner/reviewer decisions.
- The existing 200-entry dating limit remains. Directories, deletions and refused/incomplete reads stay explicitly
  unevaluated. A real local dashboard showed these unknown states; no green coverage claim was substituted.
- A clean session has no temporal notice. Saving/reformatting a ledger can remove that signal without proving
  all work is associated. Explicit file-to-lot declarations remain outside this V1.
- The browser journey used the tasks adapter on Windows Chrome. Other browsers, physical devices and assistive
  technology were not qualified by that journey; other adapters and refusal cases have automated coverage.
