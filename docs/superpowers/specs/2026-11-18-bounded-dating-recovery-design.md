<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Bounded activity dating recovery

The owner requested diagnosing and correcting the unevaluated Scout associations on 2026-11-18.

## Confirmed causes

The existing bounded ignore traversal already discovers files under untracked directories, but activity dating
receives only each top-level directory name. Every such directory therefore makes dating incomplete. One
checkout has one ordinary leaf under such a directory and can be dated completely. A larger worktree already
has more than 223 ordinary leaves plus an unresolved bounded subtree: it cannot honestly be declared complete
under MAX_DATED=200. Another reciprocal, plain same-repository worktree is missing from the exact-root options.

## Correction

Keep candidate counters unchanged. Reuse existing guarded directory enumeration and retained non-following
metadata to construct nonignored leaf observations. Do not add a recursive walk or Git command. Apply the global
200-entry dating cap after filtering; keep depth, entry limits, unsafe/special entries, deletion, nested Git,
unresolved folders and failed ignore checks explicit. No filesystem observations survive a snapshot.

Preserve legacy activity observations, but separately expose `file_activity_observed_at`: the newest safely
observed ordinary-file time in the bounded sample. The activity-date display and tracking comparison use this
ordinary-file observation. `file_activity_complete` retains its strict meaning. Expose bounded fixed reason codes
in `file_activity_partial_reasons` so the UI can explain limitations without exposing paths.

A partial sample can prove that an ordinary file was observed newer than a valid working ledger. It cannot prove
that no newer/unassociated work exists. Therefore:

- Proven newer ordinary-file activity may produce `check` or `info` under the existing task-state rules, even
  when dating is incomplete. Always display the partial-observation caveat and reason alongside it.
- Incomplete dating without that positive evidence remains `unknown`, never `none` or a coverage verdict.
- Unreadable/refused roots, invalid/merging ledgers, untrusted observations, invalid dates and unknown task states
  remain `unknown`. A directory timestamp alone never supplies positive file evidence.
- Failed ignore evaluation must not let potentially ignored files supply trusted positive observations.
- Task statuses, progress, history and owner/reviewer decisions remain unchanged.

## Local delivery

Add only the independently verified exact replay worktree of the same Scout repository to Scout's saved command.
Preserve the existing exact root and every other board's configuration. Treat the current explicit correction
request as authorization for this narrowly necessary read scope; do not authorize its parent or other descendants.
Update installed code with backup and rollback, restarting only Scout and its supervisor. Verify the other eight
board identities remain unchanged. No project source, ledger, branch or remote is modified by this correction.

## Validation

Use RED/GREEN tests for a recent leaf under an old directory, ancestor ignores, same-reader freshness, global caps,
depth/nested-Git/links/deletions, failed ignore checks, partial positive evidence and partial negative unknowns.
Verify counter and parallel/sequential equivalence, no extra walk/Git command, and guarded metadata reuse. Run
the full suite, independent Python/JS/general reviews, then real Scout API/browser/config/process checks.
