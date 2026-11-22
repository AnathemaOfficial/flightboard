<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Git/GitHub publication overview — first delivery

Flightboard must show local work even when local `main` equals its cached remote
reference. Publication facts are independent of task status and of session-card
limits. This delivery adds a publication queue, worktree coverage, explicit
remote-observation freshness, and alerts. It does not publish code or activate
product gates.

## Evidence rules

- Count the union of local commits once; stacked branch counts are not additive.
- Missing upstream configuration does not prove a commit is unpublished.
- Distinguish live GitHub observations from local tracking references.
- Missing objects, shallow history, capped reads, expired observations, and
  excluded worktrees remain visibly incomplete.
- Read working-file coverage separately from committed-ledger availability.
- A commit date is not a push date or the start of a publication delay. Delay
  starts at the first actual observation, and resets when the process restarts.

## Performance and access

The existing bounded, cached, parallel local reader stays in place. Publication
uses one cached bounded commit graph, shared across the queue and alerts.
Optional `--github` enables a separate read-only background observer using the
existing GitHub CLI login. It caches branch heads and open PR metadata for five
minutes, with bounded processes, pagination, output and deadlines. Rendering and
the ten-second local poll never wait for GitHub. There is no fetch or ref write.

Worktree access still requires explicit roots. The Scout pilot adds only its
registered, individually validated worktree roots. No sibling-directory scan,
Scout publication, model call or R2 activation is part of this delivery.

## Validation

Hermetic tests cover graph grouping, incomplete evidence, coverage, observer
freshness/concurrency/failure, CLI/autostart settings and the actual page renderer.
The Scout pilot compares current Git facts with the queue, verifies coverage and
cached refreshes, and preserves all other running boards.
