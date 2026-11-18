<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Bounded dating recovery verification

Date: 2026-11-18. Scope: [correction design](superpowers/specs/2026-11-18-bounded-dating-recovery-design.md).

## Confirmed causes and correction

Untracked directories were already traversed within the ignore-reading bounds, but only their directory names
reached activity dating. Ordinary files already discovered beneath them were discarded as dating evidence.
The correction reuses those guarded, non-following metadata observations within the same snapshot. Candidate
counts remain unchanged; modified and direct files precede nested leaves under one global 200-entry dating cap.
Unchanged tracked-file metadata is not retained merely because its directory was listed.

The UI compares only a trusted ordinary-file observation with the working-ledger save time. A partial sample can
prove the existence of newer work, so it can produce a tracking check or informational notice with an explicit
partial-observation caveat. A partial sample without positive evidence remains unknown, never complete coverage.
Ignored/untrusted candidates and directory timestamps cannot supply that positive evidence. Task states, progress,
history and owner/reviewer decisions are unchanged.

## Validation

- Complete Windows suite: **586 tests in 272.407 seconds, OK, 2 skipped** (584 passed).
- Ten real Git/filesystem regressions cover old-directory/new-leaf timing, exclusion ancestry, snapshot freshness,
  one global cap, unresolved/deep/nested-Git/link/deletion cases, failed ignore evaluation, bounded metadata
  retention and direct-file sampling priority. Existing file/metadata/parallel/path-plan tests passed.
- Fifteen tracking-view tests, fourteen actual JavaScript check groups, six catalog tests, forty-six overlay tests
  and five hygiene tests passed. Python, JavaScript and integrated source reviews approved the correction.
- A real disposable Chrome run passed twelve orchestration and sixteen browser assertions. It exercised
  `none -> check -> info -> none` through automatic polling with no manual fetch or reload, verified three dates
  and a 390px viewport, and cleaned up its owned server/browser/repository. Loaded source hashes matched.
- The reviewed operational transaction passed eleven pure failure-injection tests. A cleanup-order finding was
  fixed and independently re-reviewed before live execution; configuration drift preserves concurrent edits.

## Local deployment

The 25-file runtime payload digest is
`392e637905306cd8b6a1b2eb422880c7d4737dda5802c56b5fd785de4da89169`.
Source remains a local uncommitted change on baseline `f874bbca5ec59dcaae3e63fb060e5b9d511e4d43`; no remote CI or
publication is asserted. A full payload/configuration backup and external verification receipts were retained.

Only one selected dashboard and its supervisor were restarted. Its command gained exactly one independently
verified, reciprocal same-repository worktree root; the previous exact root was retained. The other eight board
process identities and all unrelated settings were preserved. All four installed runtime copies match the
payload digest, startup is enabled/running, and the dashboard returns HTTP 200 with readable main state.

Live verification found zero unevaluated states across its three sessions: the small canonical-directory case is
fully datable with an unassigned-work check, the large worktree yields a settled-lot tracking check with explicit
depth/folder/count limitations, and the newly included clean worktree is read without a temporal notice.
This is not a claim that every file belongs to a verified lot; the two checks still require tracking reconciliation.
