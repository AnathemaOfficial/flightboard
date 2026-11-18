<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Tracking freshness V1

Approved scope: the owner accepted the proposed three dates and advisory tracking warnings on 2026-11-17.

## Intent and approach

Make observed work visible when a task ledger has not been saved recently. The Scout example had file activity
on November 17 while its working ledger was last saved on November 15; old R2 task IDs concealed new maintenance
work. A known task ID is an association hint, not proof that all changes belong to that task.

Chosen V1: reuse existing guarded metadata reads for temporal diagnostics. Explicit per-task path declarations
remain a later option: more precise, but require additional schema and agent conventions. Automatic task creation
from documents is outside this feature because file activity alone cannot establish task identity or acceptance.

## Behavior

- Display the board reading timestamp, observed local activity timestamp, and working-ledger save timestamp.
- Use actual observed file metadata for the latter two, not the document's declarative `updated_at` value or main's
  committed ledger date. Keep those existing dates truthful and separate.
- When fully readable pending work is newer than the working ledger, show **Suivi à vérifier / Tracking to check**
  if no associated task is identified or every associated task is awaiting_review, done, or dropped.
- When an associated task has any other known status (planned, ready, in_progress, blocked), show a quieter
  informational note for that same temporal gap. An unknown associated status makes the association unknown.
- Unknown task statuses, unreadable/invalid ledgers, refused roots, missing dates, merging, or incomplete activity
  dating produce **Rattachement non évalué / Association not evaluated**, never a claim of coverage.
- A no-ledger Git-only board has no new task-tracking warnings. Clean sessions need no temporal warning.
- Evaluate unreadability before deciding a session is clean: a refused root with zero reported counts is unknown.
  Evaluate all internal task associations before the 40-ID presentation cap.
- Saving or reformatting a ledger can remove the temporal signal, but must never produce a green coverage verdict.
- Diagnostics are recalculated at every reading. They do not add task transitions/events, change task statuses,
  progress, readiness rules, or owner/reviewer decisions.

## Data and bounds

- Add public session fields `ledger_file_modified_at` (ISO timestamp or empty string) and
  `file_activity_complete` (boolean).
- Retain the existing `last_write` field. Introduce `FILES.last_write_info(tree, root, names)` returning
  `(datetime | None, bool)`; preserve `last_write` as its compatibility wrapper. Collector calls the info function
  once, so no additional Git command, filesystem traversal, or metadata read is required.
- Keep the existing MAX_DATED=200 cap and authorized-root guards. Exceeding the cap, skipped/unreadable/unsafe
  entries, untracked directory timestamps, or deletions whose time cannot be observed make dating incomplete.
- Working ledger time is available only when that ledger was actually read and valid. Branch-only/refused
  worktrees cannot acquire a fabricated local timestamp.
- View computes a per-session `tracking` object with state `none`, `check`, `info`, or `unknown` plus a fixed
  reason code. Messages are localized in English and French. Agent summaries use fixed text and safe IDs only.
- Continue treating repository text as data. Do not expose absolute machine paths or add network/provider reads.

## Validation

Reproduce the Scout gap, known-ID gap, legitimate in-progress task, ledger-only edit/reformat, invalid/missing
metadata, deletion-only work, directory candidates, capped dating and root refusals. Verify no status/KPI/event
mutation and no added Git/filesystem reads. Exercise actual refresh and date rendering, failures/recovery, both
languages, and a real disposable browser page. Run the complete suite, independent Python/JavaScript/general
reviews, then update installed payloads with backup and restart only Scout and SYFOS.
