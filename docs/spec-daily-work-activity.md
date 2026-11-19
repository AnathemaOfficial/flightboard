<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Daily declared work activity

Last updated: 2026-11-19.

## Intent

Show newly declared tasks and moves to `in_progress` in the daily chart, alongside the existing review and
completion series. A day with work starting should remain visible even when no task has reached review or done.
The common Flightboard chart supports the SYFOS use case without repository-specific rendering rules.

## Counting contract

The daily view retains its 14-day window and uses the existing aware event timestamps and local-day conversion.
It covers all releases. The burnup chart's Version 1.0 selector does not filter daily movements.

| Category | Main field | Session field | Observation |
| --- | --- | --- | --- |
| Newly declared tasks | `new_main` | `new_live` | A task becomes present, with a non-null destination status. |
| Work started | `progress_main` | `progress_live` | A move's destination is `in_progress`. |
| Review | `review_main` | `review_live` | A move's destination is `awaiting_review`. |
| Completed | `done_main` | `done_live` | A move's destination is `done`. |

These are movement categories, not a count of distinct tasks. A task created directly in progress, review or done
contributes to the new-task category and its destination category. A task can also contribute multiple movements
on the same day. The caption must state this explicitly.

Main's additions are presence differences between consecutive readable ledger versions. The first historical
snapshot is a baseline, not evidence that all its tasks were created that day. Removal is not an addition.
Existing behavior for invalid, naive, out-of-window or unconvertible event timestamps remains unchanged.

Session bars use the current net declarations that the live overlay actually applied, once per task. They are not
a journal of every intermediate working-file save. A task already present in main is not new again merely because
a branch's comparison with its merge base has no earlier task. Preserve the exclusions for conflicts, collisions,
human-governed roles and unapplied declarations, and the deduplication between matching sessions and with main.
The public change/event provenance remains intact.

## Presentation

New tasks use the existing blue palette, starts amber, reviews purple and completions green. Main's segments stay
opaque and session declarations lighter. The legend, tooltip, accessible day descriptions and table expose the
same eight series and distinguish their sources in English and French. Missing new fields in an older snapshot
render as zero. Keep one interactive hit zone per day and preserve its existing focus key and table-open state.

## Performance and read boundaries

Use the complete main history events and applied session changes already available to the view, before display
limits. Do not derive counts from the selected task-detail payload or the capped visible event/change lists.

Aggregation remains a linear pass over existing events with a fixed number of counters per day. Rendering adds
only a bounded number of chart segments. No new Git commands, file reads, history scans, collector work, cache
invalidation, polling requests, listeners per segment, or authorized roots are required. Existing read budgets,
initial loading, refresh timing, visibility handling and failure recovery remain unchanged. The application
continues to read repositories without changing their task statuses or files.

## Validation plan

- Exercise the eight counters, creation-only and start-only days, overlapping categories, removals, invalid dates,
  local-day boundaries and an initial historical baseline.
- Check that a branch advancing a task already added to main does not create a second new-task count. Preserve
  duplicate-source, governed-role, conflict and main/session exclusion cases.
- Check the daily API field contract and that complete source events survive presentation caps.
- Execute the actual daily renderer with creation/start-only data, older snapshots and empty data. Check that
  legend, table, tooltip and accessible descriptions share the same categories, with one day hit zone.
- Run the focused Python/optional-Node checks, then the full repository suite before local installation:

```powershell
rtk proxy python -I -B -m unittest discover -s tests -t . -p test_daily_activity.py -v
rtk proxy python -I -B -m unittest discover -s tests -t . -p test_live_page.py -v
rtk proxy python -I -B -m unittest discover -s tests -t .
```

This is an implementation contract and validation plan, not a test receipt or deployment claim. Loading the new
renderer in an already open tab requires a one-time HTML reload; subsequent data and status updates retain the
existing automatic refresh behavior.
