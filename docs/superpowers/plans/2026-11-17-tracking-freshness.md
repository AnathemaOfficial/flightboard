<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Tracking Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Expose three distinct dates and advisory tracking gaps without inventing task progress.

**Architecture:** Collector reuses guarded file metadata and reports dating completeness. View classifies
session diagnostics; the existing page renders localized dates and notices on every refresh.

**Tech Stack:** Python 3.12+ standard library, existing HTML/JavaScript, unittest and optional Node/browser checks.

**Spec:** `docs/superpowers/specs/2026-11-17-tracking-freshness-design.md`

## Global Constraints

- MAX_DATED=200; no new Git commands, metadata reads, dependency, provider calls, or read-root authorization.
- Preserve existing performance changes and all parallel/uncommitted work.
- No task/status/KPI/event/readiness or owner/reviewer-decision changes from diagnostics.
- Local installation only, with backup; restart only Scout and SYFOS. No commit/push/merge in this task.

## Review Focus

- A known old task ID must not hide a temporal gap involving review/done tasks.
- A legitimate in-progress task must receive information rather than a false missing-lot assertion.
- Partial dating, directory mtimes, deletion-only work and refused roots must remain unknown.
- Saving only the ledger must not fabricate progress, activity coverage or acceptance.
- Refresh failure/recovery must remove stale diagnostic/date claims and preserve focus/accessibility.

### Task 1: Guarded metadata and completeness

**Files:** `files.py`, `collector.py`, new `tests/test_tracking_metadata.py`.

**Interfaces:** `last_write_info(tree, root, names) -> tuple[datetime | None, bool]`; public session fields
`ledger_file_modified_at: str`, `file_activity_complete: bool`. Existing `last_write` behavior remains compatible.

- [x] Write real temporary-repository tests for file/ledger date separation and unreadable/partial cases.
- [x] Run the new test file and observe expected failures before implementation.
- [x] Implement the single metadata pass and public session fields, preserving successful immutable caches.
- [x] Run metadata/files/path-plan/parallel-reading tests and inspect metadata/Git call counts.

### Task 2: Classification and live presentation

**Files:** `view.py`, `messages.py`, `template.html`, new tracking view tests and existing live-page checks.

**Interfaces:** Consume Task 1 fields. Produce `tracking = {state, reason}` for every public session, using only
fixed codes. `none` means no diagnostic, never proven coverage. Localize the fixed messages for HTML and resume.

- [x] Write failing classification tests for every spec condition and assert existing KPIs/events stay equal.
- [x] Write failing live-page checks for three dates, the two notice severities and unknown/failure/recovery.
- [x] Implement the pure classification, localized notices and date rendering in existing layout.
- [x] Run focused view/catalog/live-page tests and inspect hostile text/date handling.

### Task 3: Final verification and local delivery

**Files:** Existing deployment helper and disposable probe artifacts; verification documentation.

- [x] Independently review Python, JavaScript and the integrated change; resolve findings.
- [x] Run `rtk test python -I -B -m unittest discover -s tests -t .` with the verified interpreter after code is stable.
- [x] Exercise automatic browser refresh against a disposable repository with a real temporal gap.
- [x] Verify source/performance preservation, payload digest, configuration and nine process identities.
- [x] Use the reviewed backup/deployment helper with the final digest, restarting only Scout/SYFOS.
- [x] Verify installed copies, live dates/diagnostics, autostart and seven unchanged board processes; record limits.
